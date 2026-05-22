# ADR-0006: GitHub Actions Docker Image Publishing

**Status:** Implemented
**Date:** 2026-01-18
**Deciders:** Project Owner

---

## Context

The Checkpoint Pi-hole application is containerized and needs an automated way to build and publish Docker images. Currently, images must be built manually. We need a CI/CD pipeline that:

- Automatically publishes images when code is merged to the main branch
- Allows manual image builds for testing or hotfixes
- Creates versioned releases via Git tags
- Uses GitHub Container Registry (ghcr.io) for image hosting

---

## Decision

Implement a GitHub Actions workflow to build and publish Docker images to GitHub Container Registry (ghcr.io).

### Trigger Events

| Trigger | Use Case | Image Tags |
|---------|----------|------------|
| Push to `main`/`master` | Continuous deployment of latest changes | `latest`, `main`, `sha-<commit>` |
| Manual (`workflow_dispatch`) | Testing, hotfixes, pre-release builds | `manual-<sha>`, custom input tag |
| Tag push (`v*`) | Versioned releases | `v1.0.0`, `1.0.0`, `1.0`, `1`, `latest` |

### Registry Choice: GitHub Container Registry (ghcr.io)

**Rationale:**
- Native GitHub integration (no external credentials needed)
- Free for public repositories
- Supports OCI image format
- Automatic linking to repository
- Built-in vulnerability scanning

**Image Name:** `ghcr.io/<owner>/checkpoint-pihole`

### Workflow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions Workflow                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Triggers:                                                  │
│  ├── push: main/master                                      │
│  ├── workflow_dispatch (manual)                             │
│  └── push: tags v*                                          │
│                                                             │
│  Jobs:                                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  build-and-push                                      │   │
│  │  ├── Checkout code                                   │   │
│  │  ├── Set up Docker Buildx                            │   │
│  │  ├── Login to ghcr.io                                │   │
│  │  ├── Extract metadata (tags, labels)                 │   │
│  │  ├── Build and push image                            │   │
│  │  └── Generate build summary                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Tagging Strategy

#### Semantic Versioning Tags

When a Git tag like `v1.2.3` is pushed:

| Docker Tag | Description |
|------------|-------------|
| `v1.2.3` | Exact version |
| `1.2.3` | Exact version (without v prefix) |
| `1.2` | Minor version (rolling) |
| `1` | Major version (rolling) |
| `latest` | Latest stable release |

#### Branch Tags

| Git Ref | Docker Tags |
|---------|-------------|
| `main` branch | `latest`, `main`, `sha-abc1234` |
| `master` branch | `latest`, `master`, `sha-abc1234` |

#### Manual Dispatch Tags

| Input | Docker Tags |
|-------|-------------|
| No custom tag | `manual-<sha>` |
| Custom tag provided | Custom tag value |

### Multi-Platform Support

Build images for multiple architectures:
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64, e.g., Raspberry Pi 4, Apple Silicon)

This ensures compatibility with various Pi-hole deployment environments.

---

## Workflow Implementation

```yaml
# .github/workflows/docker-publish.yml
name: Build and Publish Docker Image

on:
  push:
    branches:
      - main
      - master
    tags:
      - 'v*'
  workflow_dispatch:
    inputs:
      tag:
        description: 'Custom image tag (optional)'
        required: false
        type: string

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      attestations: write
      id-token: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata (tags, labels)
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            # Set latest tag for default branch
            type=raw,value=latest,enable={{is_default_branch}}
            # Branch name
            type=ref,event=branch
            # Semantic versioning from tags
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            # Short SHA
            type=sha,prefix=sha-
            # Manual dispatch with custom tag
            type=raw,value=${{ inputs.tag }},enable=${{ inputs.tag != '' }}
            # Manual dispatch fallback
            type=raw,value=manual-${{ github.sha }},enable=${{ github.event_name == 'workflow_dispatch' && inputs.tag == '' }}

      - name: Build and push Docker image
        id: push
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Generate artifact attestation
        uses: actions/attest-build-provenance@v2
        with:
          subject-name: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          subject-digest: ${{ steps.push.outputs.digest }}
          push-to-registry: true
```

---

## Repository Configuration Required

### 1. Package Visibility

After first publish, configure package visibility:
- Go to repository Settings > Packages
- Set visibility to Public (or Private as needed)
- Link package to repository for README display

### 2. Branch Protection (Recommended)

Protect the main branch to prevent accidental pushes:
- Require pull request reviews
- Require status checks to pass
- Prevent force pushes

### 3. No Additional Secrets Required

The workflow uses `GITHUB_TOKEN` which is automatically provided.

---

## Usage Examples

### Pull Latest Image

```bash
docker pull ghcr.io/<owner>/checkpoint-pihole:latest
```

### Pull Specific Version

```bash
docker pull ghcr.io/<owner>/checkpoint-pihole:v1.0.0
docker pull ghcr.io/<owner>/checkpoint-pihole:1.0
```

### Pull Specific Commit

```bash
docker pull ghcr.io/<owner>/checkpoint-pihole:sha-abc1234
```

### Update docker-compose.yml

```yaml
services:
  checkpoint-pihole:
    image: ghcr.io/<owner>/checkpoint-pihole:latest
    # or for production: ghcr.io/<owner>/checkpoint-pihole:v1.0.0
```

---

## Creating a Release

1. **Update version** (if applicable in code)

2. **Create and push tag:**
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```

3. **Workflow automatically:**
   - Builds multi-arch image
   - Tags with `v1.0.0`, `1.0.0`, `1.0`, `1`, `latest`
   - Pushes to ghcr.io
   - Creates attestation

4. **Create GitHub Release** (optional):
   - Go to Releases > Draft new release
   - Select the tag
   - Auto-generate release notes
   - Publish

---

## Manual Dispatch Usage

### Via GitHub UI

1. Go to Actions > Build and Publish Docker Image
2. Click "Run workflow"
3. Optionally enter custom tag
4. Click "Run workflow"

### Via GitHub CLI

```bash
# Default tags
gh workflow run docker-publish.yml

# With custom tag
gh workflow run docker-publish.yml -f tag=my-custom-tag
```

---

## Build Optimization

### Layer Caching

The workflow uses GitHub Actions cache for Docker layers:
- `cache-from: type=gha` - Pull cache from previous builds
- `cache-to: type=gha,mode=max` - Push all layers to cache

This significantly speeds up subsequent builds.

### Multi-Stage Build (Future Enhancement)

Consider optimizing the Dockerfile with multi-stage builds:
- Stage 1: Install dependencies
- Stage 2: Copy only runtime files
- Reduces final image size

---

## Monitoring and Troubleshooting

### Check Build Status

- GitHub Actions tab shows workflow runs
- Click on a run for detailed logs
- Failed builds show error details

### Common Issues

| Issue | Solution |
|-------|----------|
| Permission denied to ghcr.io | Check `packages: write` permission in workflow |
| Image not visible | Set package visibility in repository settings |
| ARM64 build slow | QEMU emulation is slower; consider self-hosted ARM runners for speed |
| Cache miss | First build or workflow change clears cache |

### Verify Published Image

```bash
# List tags
docker manifest inspect ghcr.io/<owner>/checkpoint-pihole:latest

# Check multi-arch support
docker manifest inspect ghcr.io/<owner>/checkpoint-pihole:latest | jq '.manifests[].platform'
```

---

## Consequences

### Positive

- Automated image publishing on merge
- Consistent, reproducible builds
- Multi-architecture support (amd64 + arm64)
- Version history via tags
- Build provenance attestation for supply chain security
- No external registry credentials needed
- Free for public repositories

### Negative

- Initial setup and testing required
- Multi-arch builds take longer (~5-10 min)
- GitHub-specific solution (vendor lock-in)
- Cache storage counts against GitHub storage limits

### Mitigations

- Use build cache to speed up subsequent builds
- Consider splitting into separate arch-specific builds if needed
- Workflow is portable to other CI systems with minor changes
- Monitor cache usage in repository settings

---

## Future Enhancements

1. **Add test job before publish** - Run tests, only publish if passing
2. **Security scanning** - Add Trivy or Snyk vulnerability scanning
3. **SBOM generation** - Software Bill of Materials for compliance
4. **Slack/Discord notifications** - Notify on publish success/failure
5. **Automatic GitHub Release** - Create release with changelog on tag

---

## References

- [GitHub Actions: Publishing Docker images](https://docs.github.com/en/actions/publishing-packages/publishing-docker-images)
- [docker/build-push-action](https://github.com/docker/build-push-action)
- [docker/metadata-action](https://github.com/docker/metadata-action)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Build Provenance Attestation](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)
