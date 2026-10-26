#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_DIR="$REPO_ROOT/infra/terraform"
WEBSITE_DIR="$REPO_ROOT/website"
DEPLOY_SITE=true
DEPLOY_NPM=true
APPLY_INFRA=false
DRY_RUN=false
YES=false
TEMP_NPMRC=""
AUTO_VERSION=true
VERSION_BUMP="patch"
EXPLICIT_VERSION=""
VERSION_GIT=true
VERSION_CHANGED=false
VERSION_GIT_ACTIVE=false
VERSION_FILES=(package.json pyproject.toml loki_cli/__init__.py apps/desktop/package.json uv.lock package-lock.json)

cleanup() {
  if [ -n "$TEMP_NPMRC" ] && [ -f "$TEMP_NPMRC" ]; then
    rm -f "$TEMP_NPMRC"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'USAGE'
Usage: ./scripts/deploy.sh [options]

Options:
  --site-only        Deploy only loki.computer
  --npm-only         Publish only @wundercorp/loki
  --with-infra       Run terraform init/plan/apply before site upload
  --dry-run          Build and validate without publishing or uploading
  --yes              Skip the production confirmation prompt
  --bump PART        Auto-version collision bump: patch, minor, or major (default: patch)
  --version X.Y.Z    Publish an explicit version and synchronize all version metadata
  --no-auto-version  Do not choose a new version automatically; fail on registry collisions
  --no-version-git   Allow a non-git/dirty release and do not commit/push version metadata
  -h, --help         Show this help

Environment:
  NPM_TOKEN                               Optional npm automation token
  LOKI_SITE_BUCKET                       Optional S3 bucket override; defaults to loki.computer
  LOKI_CLOUDFRONT_DISTRIBUTION_ID        Optional CloudFront distribution override
  LOKI_SITE_DOMAIN                       Optional site domain override; defaults to loki.computer
  LOKI_TERRAFORM_STATE_BUCKET            Optional Terraform state bucket override
  LOKI_TERRAFORM_STATE_KEY               Optional Terraform state object key
  TF_VAR_hosted_zone_id                  Optional override; defaults to loki.computer zone Z09046593O6AIZUOSG6X8
  AWS_PROFILE                             Optional AWS CLI profile
  AWS_REGION                              Optional AWS region, defaults to us-east-1
  LOKI_VERSION_BUMP                       Optional default bump component: patch, minor, or major
  LOKI_NPM_CONFIRM_ATTEMPTS                Registry confirmation polls after successful npm publish (default: 24)
  LOKI_NPM_CONFIRM_DELAY                   Seconds between confirmation polls (default: 5)
  LOKI_RELEASE_BRANCH                      Production source branch used by install.sh (default: main)
  LOKI_EXPECTED_RELEASE_ORIGIN             Expected standalone Loki repository
                                               (default: https://github.com/wundercorp/loki.git)
  LOKI_ALLOW_NON_RELEASE_BRANCH_DEPLOY     Set to 1 only to intentionally deploy from another branch
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

resolve_cloudfront_distribution_id() {
  local distribution_id="${LOKI_CLOUDFRONT_DISTRIBUTION_ID:-}"
  local terraform_distribution_id=""
  local cloudfront_distributions=""

  if [ -n "$distribution_id" ]; then
    printf '%s' "$distribution_id"
    return 0
  fi

  if command -v terraform >/dev/null 2>&1; then
    terraform_distribution_id="$(terraform -chdir="$TERRAFORM_DIR" output -raw cloudfront_distribution_id 2>/dev/null || true)"
    if [ -n "$terraform_distribution_id" ] && [ "$terraform_distribution_id" != "None" ]; then
      printf '%s' "$terraform_distribution_id"
      return 0
    fi
  fi

  cloudfront_distributions="$(aws cloudfront list-distributions --output json 2>/dev/null || true)"
  if [ -n "$cloudfront_distributions" ]; then
    printf '%s' "$cloudfront_distributions" | node -e '
const fs = require("fs");
const domain = process.argv[1];
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const distributions = payload.DistributionList?.Items ?? [];
const match = distributions.find(item => (item.Aliases?.Items ?? []).includes(domain));
process.stdout.write(match?.Id ?? "");
' "$SITE_DOMAIN"
  fi
}

site_infrastructure_status() {
  SITE_BUCKET_READY=false
  CLOUDFRONT_READY=false
  PREFLIGHT_DISTRIBUTION_ID=""

  if aws s3api head-bucket --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
    SITE_BUCKET_READY=true
  fi

  PREFLIGHT_DISTRIBUTION_ID="$(resolve_cloudfront_distribution_id)"
  if [ -n "$PREFLIGHT_DISTRIBUTION_ID" ] && [ "$PREFLIGHT_DISTRIBUTION_ID" != "None" ]; then
    CLOUDFRONT_READY=true
  fi

  $SITE_BUCKET_READY && $CLOUDFRONT_READY
}


terraform_state_has() {
  terraform -chdir="$TERRAFORM_DIR" state show "$1" >/dev/null 2>&1
}

terraform_import_if_missing() {
  local address="$1"
  local import_id="$2"

  if [ -z "$import_id" ] || [ "$import_id" = "None" ] || [ "$import_id" = "null" ]; then
    return 0
  fi
  if terraform_state_has "$address"; then
    return 0
  fi

  printf 'Adopting existing AWS resource into Terraform state: %s\n' "$address"
  terraform -chdir="$TERRAFORM_DIR" import -input=false "$address" "$import_id"
}

ensure_terraform_state_bucket() {
  local account_id="$1"
  TERRAFORM_STATE_BUCKET="${LOKI_TERRAFORM_STATE_BUCKET:-wundercorp-loki-terraform-state-${account_id}}"
  TERRAFORM_STATE_KEY="${LOKI_TERRAFORM_STATE_KEY:-loki-agent/production/terraform.tfstate}"

  if aws s3api head-bucket --bucket "$TERRAFORM_STATE_BUCKET" >/dev/null 2>&1; then
    return 0
  fi

  printf 'Creating durable Terraform state bucket s3://%s\n' "$TERRAFORM_STATE_BUCKET"
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$TERRAFORM_STATE_BUCKET" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "$TERRAFORM_STATE_BUCKET" \
      --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
  aws s3api put-bucket-versioning \
    --bucket "$TERRAFORM_STATE_BUCKET" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption \
    --bucket "$TERRAFORM_STATE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block \
    --bucket "$TERRAFORM_STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
}

initialize_terraform_backend() {
  if [ -s "$TERRAFORM_DIR/terraform.tfstate" ]; then
    printf 'Migrating local Terraform state to s3://%s/%s\n' "$TERRAFORM_STATE_BUCKET" "$TERRAFORM_STATE_KEY"
    terraform -chdir="$TERRAFORM_DIR" init \
      -input=false \
      -migrate-state \
      -force-copy \
      -backend-config="bucket=$TERRAFORM_STATE_BUCKET" \
      -backend-config="key=$TERRAFORM_STATE_KEY" \
      -backend-config="region=$AWS_REGION" \
      -backend-config="encrypt=true"
  else
    terraform -chdir="$TERRAFORM_DIR" init \
      -input=false \
      -reconfigure \
      -backend-config="bucket=$TERRAFORM_STATE_BUCKET" \
      -backend-config="key=$TERRAFORM_STATE_KEY" \
      -backend-config="region=$AWS_REGION" \
      -backend-config="encrypt=true"
  fi
}
cloudfront_oac_id_by_name() {
  local name="$1"
  aws cloudfront list-origin-access-controls --output json 2>/dev/null | node -e '
const fs = require("fs");
const name = process.argv[1];
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const items = payload.OriginAccessControlList?.Items ?? [];
const match = items.find(item => (item.OriginAccessControlConfig ?? item).Name === name);
process.stdout.write(match?.Id ?? "");
' "$name"
}

cloudfront_response_headers_policy_id_by_name() {
  local name="$1"
  aws cloudfront list-response-headers-policies --type custom --output json 2>/dev/null | node -e '
const fs = require("fs");
const name = process.argv[1];
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const items = payload.ResponseHeadersPolicyList?.Items ?? [];
const match = items.find(item => {
  const policy = item.ResponseHeadersPolicy ?? item;
  return policy.ResponseHeadersPolicyConfig?.Name === name;
});
const policy = match?.ResponseHeadersPolicy ?? match;
process.stdout.write(policy?.Id ?? "");
' "$name"
}

acm_certificate_arn_for_domain() {
  local domain="$1"
  aws acm list-certificates \
    --region us-east-1 \
    --certificate-statuses ISSUED PENDING_VALIDATION \
    --output json 2>/dev/null | node -e '
const fs = require("fs");
const domain = process.argv[1];
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const certs = (payload.CertificateSummaryList ?? []).filter(cert => cert.DomainName === domain);
const issued = certs.find(cert => cert.Status === "ISSUED");
process.stdout.write((issued ?? certs[0])?.CertificateArn ?? "");
' "$domain"
}

route53_record_exists() {
  local zone_id="$1"
  local record_name="$2"
  local record_type="$3"
  aws route53 list-resource-record-sets \
    --hosted-zone-id "$zone_id" \
    --output json 2>/dev/null | node -e '
const fs = require("fs");
const [name, type] = process.argv.slice(1);
const normalize = value => value.endsWith(".") ? value : `${value}.`;
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const exists = (payload.ResourceRecordSets ?? []).some(record => normalize(record.Name) === normalize(name) && record.Type === type);
process.stdout.write(exists ? "yes" : "");
' "$record_name" "$record_type"
}

reconcile_existing_terraform_resources() {
  local hosted_zone_id="${TF_VAR_hosted_zone_id:-Z09046593O6AIZUOSG6X8}"
  local oac_name="${SITE_DOMAIN}-oac"
  local security_policy_name="${SITE_DOMAIN//./-}-security"
  local site_router_name="${SITE_DOMAIN//./-}-site-router"
  local doku_router_name="${SITE_DOMAIN//./-}-doku-router"
  local existing_id=""
  local certificate_arn=""
  local validation_json=""
  local validation_name=""
  local validation_type=""

  if aws s3api head-bucket --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
    terraform_import_if_missing 'aws_s3_bucket.site' "$SITE_BUCKET"
    if [ -n "$(aws s3api get-bucket-versioning --bucket "$SITE_BUCKET" --query Status --output text 2>/dev/null || true)" ]; then
      terraform_import_if_missing 'aws_s3_bucket_versioning.site' "$SITE_BUCKET"
    fi
    if aws s3api get-bucket-encryption --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
      terraform_import_if_missing 'aws_s3_bucket_server_side_encryption_configuration.site' "$SITE_BUCKET"
    fi
    if aws s3api get-public-access-block --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
      terraform_import_if_missing 'aws_s3_bucket_public_access_block.site' "$SITE_BUCKET"
    fi
    if aws s3api get-bucket-policy --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
      terraform_import_if_missing 'aws_s3_bucket_policy.site' "$SITE_BUCKET"
    fi
  fi

  existing_id="$(cloudfront_oac_id_by_name "$oac_name")"
  terraform_import_if_missing 'aws_cloudfront_origin_access_control.site' "$existing_id"

  existing_id="$(cloudfront_response_headers_policy_id_by_name "$security_policy_name")"
  terraform_import_if_missing 'aws_cloudfront_response_headers_policy.security' "$existing_id"

  if aws cloudfront describe-function --name "$site_router_name" >/dev/null 2>&1; then
    terraform_import_if_missing 'aws_cloudfront_function.site_router' "$site_router_name"
  fi
  if aws cloudfront describe-function --name "$doku_router_name" >/dev/null 2>&1; then
    terraform_import_if_missing 'aws_cloudfront_function.doku_router' "$doku_router_name"
  fi

  if terraform_state_has 'aws_acm_certificate.site'; then
    certificate_arn="$(terraform -chdir="$TERRAFORM_DIR" state show -no-color 'aws_acm_certificate.site' 2>/dev/null | sed -n 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' | head -n 1)"
  else
    certificate_arn="$(acm_certificate_arn_for_domain "$SITE_DOMAIN")"
  fi
  if [ -n "$certificate_arn" ]; then
    terraform_import_if_missing 'aws_acm_certificate.site' "$certificate_arn"

    validation_json="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$certificate_arn" --output json 2>/dev/null || true)"
    if [ -n "$validation_json" ]; then
      validation_name="$(printf '%s' "$validation_json" | node -e '
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(payload.Certificate?.DomainValidationOptions?.[0]?.ResourceRecord?.Name ?? "");
')"
      validation_type="$(printf '%s' "$validation_json" | node -e '
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(payload.Certificate?.DomainValidationOptions?.[0]?.ResourceRecord?.Type ?? "");
')"
      if [ -n "$validation_name" ] && [ -n "$validation_type" ] && [ -n "$(route53_record_exists "$hosted_zone_id" "$validation_name" "$validation_type")" ]; then
        local validation_address="aws_route53_record.certificate_validation[\"${SITE_DOMAIN}\"]"
        terraform_import_if_missing \
          "$validation_address" \
          "${hosted_zone_id}_${validation_name}_${validation_type}"
      fi
    fi
  fi

  existing_id="$(resolve_cloudfront_distribution_id)"
  terraform_import_if_missing 'aws_cloudfront_distribution.site' "$existing_id"

  if [ -n "$(route53_record_exists "$hosted_zone_id" "$SITE_DOMAIN" A)" ]; then
    terraform_import_if_missing 'aws_route53_record.site_a' "${hosted_zone_id}_${SITE_DOMAIN}_A"
  fi
  if [ -n "$(route53_record_exists "$hosted_zone_id" "$SITE_DOMAIN" AAAA)" ]; then
    terraform_import_if_missing 'aws_route53_record.site_aaaa' "${hosted_zone_id}_${SITE_DOMAIN}_AAAA"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --site-only)
      DEPLOY_SITE=true
      DEPLOY_NPM=false
      ;;
    --npm-only)
      DEPLOY_SITE=false
      DEPLOY_NPM=true
      ;;
    --with-infra)
      APPLY_INFRA=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --yes)
      YES=true
      ;;
    --bump)
      if [ "$#" -lt 2 ]; then
        printf '%s\n' '--bump requires patch, minor, or major.' >&2
        exit 1
      fi
      VERSION_BUMP="$2"
      case "$VERSION_BUMP" in
        patch|minor|major) ;;
        *) printf 'Invalid --bump value: %s\n' "$VERSION_BUMP" >&2; exit 1 ;;
      esac
      shift
      ;;
    --version)
      if [ "$#" -lt 2 ]; then
        printf '%s\n' '--version requires X.Y.Z.' >&2
        exit 1
      fi
      EXPLICIT_VERSION="$2"
      shift
      ;;
    --no-auto-version)
      AUTO_VERSION=false
      ;;
    --no-version-git)
      VERSION_GIT=false
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

require_command node
require_command npm
require_command python3

VERSION_BUMP="${LOKI_VERSION_BUMP:-$VERSION_BUMP}"
case "$VERSION_BUMP" in
  patch|minor|major) ;;
  *) printf 'Invalid LOKI_VERSION_BUMP/--bump value: %s\n' "$VERSION_BUMP" >&2; exit 1 ;;
esac

if $DEPLOY_SITE && ! $DRY_RUN; then
  require_command aws
fi

if $APPLY_INFRA && ! $DEPLOY_SITE; then
  printf '%s\n' '--with-infra requires site deployment.' >&2
  exit 1
fi

cd "$REPO_ROOT"

RELEASE_BRANCH="${LOKI_RELEASE_BRANCH:-main}"
EXPECTED_RELEASE_ORIGIN="${LOKI_EXPECTED_RELEASE_ORIGIN:-https://github.com/wundercorp/loki.git}"
ALLOW_NON_RELEASE_BRANCH_DEPLOY="${LOKI_ALLOW_NON_RELEASE_BRANCH_DEPLOY:-0}"

normalize_git_url() {
  printf '%s' "$1" \
    | sed -E \
        -e 's#^git@github\.com:#https://github.com/#' \
        -e 's#\.git$##' \
        -e 's#/$##'
}

verify_release_origin() {
  local origin_url
  local normalized_origin
  local normalized_expected

  origin_url="$(git remote get-url origin 2>/dev/null || true)"

  if [ -z "$origin_url" ]; then
    printf '%s\n' \
      'ERROR: standalone Loki releases require an origin remote.' \
      >&2
    exit 1
  fi

  normalized_origin="$(normalize_git_url "$origin_url")"
  normalized_expected="$(normalize_git_url "$EXPECTED_RELEASE_ORIGIN")"

  if [ "$normalized_origin" != "$normalized_expected" ]; then
    printf '%s\n' \
      'ERROR: this checkout does not point at the expected standalone Loki repository.' \
      >&2

    printf 'Expected: %s\n' \
      "$EXPECTED_RELEASE_ORIGIN" \
      >&2

    printf 'Actual:   %s\n' \
      "$origin_url" \
      >&2

    exit 1
  fi
}

push_release_source() {
  local source_commit
  local remote_commit

  verify_release_origin

  source_commit="$(git rev-parse HEAD)"

  printf 'Publishing Loki source to origin (%s)...\n' \
    "$RELEASE_BRANCH"

  git push \
    origin \
    "HEAD:refs/heads/$RELEASE_BRANCH"

  remote_commit="$(
    git ls-remote \
      origin \
      "refs/heads/$RELEASE_BRANCH" \
    | awk 'NR == 1 {print $1}'
  )"

  if [ -z "$remote_commit" ]; then
    printf '%s\n' \
      'ERROR: origin did not report a release branch commit.' \
      >&2
    exit 1
  fi

  if [ "$remote_commit" != "$source_commit" ]; then
    printf '%s\n' \
      'ERROR: release source verification failed.' \
      >&2

    printf 'Local HEAD: %s\n' \
      "$source_commit" \
      >&2

    printf 'Remote %s: %s\n' \
      "$RELEASE_BRANCH" \
      "$remote_commit" \
      >&2

    exit 1
  fi

  printf 'Verified standalone Loki release source: %s@%s\n' \
    "$RELEASE_BRANCH" \
    "${source_commit:0:12}"
}

if ! $DRY_RUN && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
  if [ -n "$DEPLOY_BRANCH" ] && [ "$DEPLOY_BRANCH" != "$RELEASE_BRANCH" ] \
     && [ "$ALLOW_NON_RELEASE_BRANCH_DEPLOY" != "1" ]; then
    printf 'Refusing production deploy from branch %s.\n' "$DEPLOY_BRANCH" >&2
    printf 'The public installer clones %s by default, so publishing from another branch can make loki.computer/install.sh install older code.\n' "$RELEASE_BRANCH" >&2
    printf 'Merge/switch to %s first, or set LOKI_ALLOW_NON_RELEASE_BRANCH_DEPLOY=1 only when this mismatch is intentional.\n' "$RELEASE_BRANCH" >&2
    exit 1
  fi
fi

if ! $DRY_RUN && ! $YES; then
  printf 'This will deploy%s%s. Continue? [y/N] ' \
    "$($DEPLOY_SITE && printf ' loki.computer' || true)" \
    "$($DEPLOY_NPM && printf ' @wundercorp/loki' || true)"
  read -r confirmation
  case "$confirmation" in
    y|Y|yes|YES) ;;
    *) printf '%s\n' 'Cancelled.'; exit 1 ;;
  esac
fi

SITE_DOMAIN="${LOKI_SITE_DOMAIN:-loki.computer}"
SITE_BUCKET="${LOKI_SITE_BUCKET:-$SITE_DOMAIN}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

if $DEPLOY_SITE && ! $DRY_RUN && ! $APPLY_INFRA; then
  aws sts get-caller-identity >/dev/null
  if ! site_infrastructure_status; then
    missing_resources=""
    if ! $SITE_BUCKET_READY; then
      missing_resources="S3 bucket $SITE_BUCKET"
    fi
    if ! $CLOUDFRONT_READY; then
      if [ -n "$missing_resources" ]; then
        missing_resources="$missing_resources and CloudFront distribution for $SITE_DOMAIN"
      else
        missing_resources="CloudFront distribution for $SITE_DOMAIN"
      fi
    fi

    if ! $YES && command -v terraform >/dev/null 2>&1; then
      printf 'Site infrastructure is incomplete (%s). Apply Terraform now? [y/N] ' "$missing_resources"
      read -r infra_confirmation
      case "$infra_confirmation" in
        y|Y|yes|YES) APPLY_INFRA=true ;;
        *)
          printf 'Site infrastructure is required before deployment. Run `%s --with-infra`.\n' "$0" >&2
          exit 1
          ;;
      esac
    else
      if $YES; then
        printf 'Site infrastructure is incomplete (%s). Re-run `%s --with-infra --yes`.\n' "$missing_resources" "$0" >&2
      else
        printf 'Site infrastructure is incomplete (%s). Run `%s --with-infra`.\n' "$missing_resources" "$0" >&2
      fi
      exit 1
    fi
  fi
fi

if $APPLY_INFRA; then
  require_command terraform
  require_command aws
  export TF_VAR_hosted_zone_id="${TF_VAR_hosted_zone_id:-Z09046593O6AIZUOSG6X8}"
  printf '\n==> Applying Terraform\n'
  aws sts get-caller-identity >/dev/null
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  terraform -chdir="$TERRAFORM_DIR" fmt -check -recursive
  ensure_terraform_state_bucket "$AWS_ACCOUNT_ID"
  initialize_terraform_backend
  terraform -chdir="$TERRAFORM_DIR" validate
  reconcile_existing_terraform_resources
  terraform -chdir="$TERRAFORM_DIR" plan -input=false -out=tfplan
  if ! $DRY_RUN; then
    terraform -chdir="$TERRAFORM_DIR" apply -input=false -auto-approve tfplan
  fi
fi

if $DEPLOY_NPM; then
  PACKAGE_NAME="$(node -p "require('./package.json').name")"
  LOCAL_VERSION="$(node -p "require('./package.json').version")"
  REGISTRY_VERSION=""
  TARGET_VERSION="$LOCAL_VERSION"

  printf '\n==> Resolving npm release version\n'

  if $VERSION_GIT && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    VERSION_GIT_ACTIVE=true
    DIRTY_WORKTREE="$(git status --porcelain)"
    if [ -n "$DIRTY_WORKTREE" ]; then
      printf '%s\n' 'Release worktree is not clean. Commit/stash all changes before deploying, or use --no-version-git intentionally.' >&2
      printf '%s\n' "$DIRTY_WORKTREE" >&2
      exit 1
    fi
  fi

  set +e
  REGISTRY_VERSION="$(npm view "$PACKAGE_NAME" version --registry=https://registry.npmjs.org --prefer-online --fetch-retries=0 2>/dev/null)"
  REGISTRY_LOOKUP_STATUS=$?
  set -e
  if [ "$REGISTRY_LOOKUP_STATUS" -ne 0 ]; then
    if npm ping --registry=https://registry.npmjs.org >/dev/null 2>&1; then
      REGISTRY_VERSION=""
    else
      printf '%s\n' 'Unable to query the npm registry. Refusing to guess a release version.' >&2
      exit 1
    fi
  fi

  if [ -n "$EXPLICIT_VERSION" ]; then
    TARGET_VERSION="$EXPLICIT_VERSION"
    python3 scripts/sync_version.py next --local "$TARGET_VERSION" --bump patch >/dev/null
    set +e
    npm view "$PACKAGE_NAME@$TARGET_VERSION" version --registry=https://registry.npmjs.org --prefer-online --fetch-retries=0 >/dev/null 2>&1
    VERSION_EXISTS=$?
    set -e
    if [ "$VERSION_EXISTS" -eq 0 ]; then
      printf '%s@%s already exists on npm; choose a new --version.\n' "$PACKAGE_NAME" "$TARGET_VERSION" >&2
      exit 1
    fi
  elif $AUTO_VERSION; then
    TARGET_VERSION="$(python3 scripts/sync_version.py next --local "$LOCAL_VERSION" --registry "$REGISTRY_VERSION" --bump "$VERSION_BUMP")"
  fi

  if [ "$TARGET_VERSION" != "$LOCAL_VERSION" ]; then
    printf 'Version plan: %s@%s -> %s (registry latest: %s)\n' \
      "$PACKAGE_NAME" "$LOCAL_VERSION" "$TARGET_VERSION" "${REGISTRY_VERSION:-none}"
    if $DRY_RUN; then
      printf 'Dry run: would synchronize release metadata to %s before publishing.\n' "$TARGET_VERSION"
    else
      RELEASE_DATE="$(python3 - <<'PYDATE'
from datetime import date
value = date.today()
print(f"{value.year}.{value.month}.{value.day}")
PYDATE
)"
      python3 scripts/sync_version.py set "$TARGET_VERSION" --date "$RELEASE_DATE"
      VERSION_CHANGED=true
    fi
  else
    if [ -n "$REGISTRY_VERSION" ] && [ "$TARGET_VERSION" = "$REGISTRY_VERSION" ]; then
      printf '%s@%s is already published and auto-versioning is disabled.\n' "$PACKAGE_NAME" "$TARGET_VERSION" >&2
      exit 1
    fi
    printf 'Version plan: publish existing local version %s (registry latest: %s).\n' \
      "$TARGET_VERSION" "${REGISTRY_VERSION:-none}"
  fi

  printf '\n==> Validating npm package\n'
  npm run release:check

  if $DRY_RUN; then
    printf 'Dry run: would publish %s@%s\n' "$PACKAGE_NAME" "$TARGET_VERSION"
  else
    if [ -n "${NPM_TOKEN:-}" ]; then
      TEMP_NPMRC="$(mktemp)"
      printf '//registry.npmjs.org/:_authToken=%s\n' "$NPM_TOKEN" > "$TEMP_NPMRC"
      chmod 600 "$TEMP_NPMRC"
      export NPM_CONFIG_USERCONFIG="$TEMP_NPMRC"
    fi

    if ! npm whoami --registry=https://registry.npmjs.org >/dev/null 2>&1; then
      printf '%s\n' 'npm authentication is required. Run `npm login` or set NPM_TOKEN.' >&2
      exit 1
    fi

    if $VERSION_GIT_ACTIVE; then
      if $VERSION_CHANGED; then
        VERSION_GIT_FILES=()
        for version_file in "${VERSION_FILES[@]}"; do
          if [ -e "$version_file" ]; then
            VERSION_GIT_FILES+=("$version_file")
          fi
        done
        git add -- "${VERSION_GIT_FILES[@]}"
        if ! git diff --cached --quiet; then
          git commit -m "chore: bump version to v$TARGET_VERSION"
        fi
      fi

      CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
      if [ -z "$CURRENT_BRANCH" ]; then
        printf '%s\n' 'Cannot publish from a detached HEAD with release git integration enabled. Re-run with --no-version-git only if that is intentional.' >&2
        exit 1
      fi
      push_release_source
    fi

    COLLISION_RETRIES=0
    while npm view "$PACKAGE_NAME@$TARGET_VERSION" version --registry=https://registry.npmjs.org --prefer-online --fetch-retries=0 >/dev/null 2>&1; do
      if ! $AUTO_VERSION || [ -n "$EXPLICIT_VERSION" ]; then
        printf '%s@%s appeared on npm before publish and cannot be auto-bumped.\n' \
          "$PACKAGE_NAME" "$TARGET_VERSION" >&2
        exit 1
      fi

      COLLISION_RETRIES=$((COLLISION_RETRIES + 1))
      if [ "$COLLISION_RETRIES" -gt 10 ]; then
        printf '%s\n' 'Too many npm version collisions; refusing to loop indefinitely.' >&2
        exit 1
      fi

      REGISTRY_VERSION="$(npm view "$PACKAGE_NAME" version --registry=https://registry.npmjs.org --prefer-online --fetch-retries=0 2>/dev/null || true)"
      NEXT_VERSION="$(python3 scripts/sync_version.py next --local "$TARGET_VERSION" --registry "$REGISTRY_VERSION" --bump "$VERSION_BUMP")"
      if [ "$NEXT_VERSION" = "$TARGET_VERSION" ]; then
        NEXT_VERSION="$(python3 scripts/sync_version.py next --local "$TARGET_VERSION" --registry "$TARGET_VERSION" --bump "$VERSION_BUMP")"
      fi

      printf '%s@%s appeared on npm before publish; advancing release to %s and retrying.\n' \
        "$PACKAGE_NAME" "$TARGET_VERSION" "$NEXT_VERSION"
      TARGET_VERSION="$NEXT_VERSION"
      RELEASE_DATE="$(python3 - <<'PYDATE2'
from datetime import date
value = date.today()
print(f"{value.year}.{value.month}.{value.day}")
PYDATE2
)"
      python3 scripts/sync_version.py set "$TARGET_VERSION" --date "$RELEASE_DATE"
      VERSION_CHANGED=true
      npm run release:check

      if $VERSION_GIT_ACTIVE; then
        VERSION_GIT_FILES=()
        for version_file in "${VERSION_FILES[@]}"; do
          if [ -e "$version_file" ]; then
            VERSION_GIT_FILES+=("$version_file")
          fi
        done
        git add -- "${VERSION_GIT_FILES[@]}"
        if ! git diff --cached --quiet; then
          git commit -m "chore: bump version to v$TARGET_VERSION"
        fi
        push_release_source
      fi
    done

    npm publish --access public --provenance=false --registry=https://registry.npmjs.org

    NPM_CONFIRM_ATTEMPTS="${LOKI_NPM_CONFIRM_ATTEMPTS:-24}"
    NPM_CONFIRM_DELAY="${LOKI_NPM_CONFIRM_DELAY:-5}"
    CONFIRMED_VERSION=""
    CONFIRM_ATTEMPT=1

    while [ "$CONFIRM_ATTEMPT" -le "$NPM_CONFIRM_ATTEMPTS" ]; do
      CONFIRMED_VERSION="$(npm view "$PACKAGE_NAME@$TARGET_VERSION" version \
        --registry=https://registry.npmjs.org \
        --prefer-online \
        --fetch-retries=0 \
        2>/dev/null || true)"

      if [ "$CONFIRMED_VERSION" = "$TARGET_VERSION" ]; then
        break
      fi

      if [ "$CONFIRM_ATTEMPT" -lt "$NPM_CONFIRM_ATTEMPTS" ]; then
        printf 'npm accepted %s@%s; registry metadata is still propagating (%s/%s).\n' \
          "$PACKAGE_NAME" "$TARGET_VERSION" "$CONFIRM_ATTEMPT" "$NPM_CONFIRM_ATTEMPTS"
        sleep "$NPM_CONFIRM_DELAY"
      fi

      CONFIRM_ATTEMPT=$((CONFIRM_ATTEMPT + 1))
    done

    if [ "$CONFIRMED_VERSION" = "$TARGET_VERSION" ]; then
      printf 'npm registry confirmed %s@%s.\n' "$PACKAGE_NAME" "$TARGET_VERSION"
    else
      printf 'WARNING: npm publish accepted %s@%s, but registry metadata has not propagated yet. Continuing deployment because npm publish exited successfully.\n' \
        "$PACKAGE_NAME" "$TARGET_VERSION" >&2
      printf 'Verify later with: npm view %s@%s version --registry=https://registry.npmjs.org --prefer-online\n' \
        "$PACKAGE_NAME" "$TARGET_VERSION" >&2
    fi
  fi
fi

# The public shell/PowerShell installers clone this standalone repository.
# A site-only deploy still synchronizes origin/main before uploading installers
# so the installer source and the deployed installer remain on the same commit.
if $DEPLOY_SITE && ! $DEPLOY_NPM && ! $DRY_RUN \
   && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -n "$(git status --porcelain)" ]; then
    printf '%s\n' 'Site-only release worktree is not clean. Commit/stash changes before deployment.' >&2
    git status --short >&2
    exit 1
  fi
  CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
  if [ -z "$CURRENT_BRANCH" ]; then
    printf '%s\n' 'Cannot publish installer source from a detached HEAD.' >&2
    exit 1
  fi
  push_release_source
fi

if $DEPLOY_SITE; then
  printf '\n==> Building loki.computer\n'
  npm --prefix "$WEBSITE_DIR" run build

  if $DRY_RUN; then
    printf 'Dry run: Loki splash site and documentation payload built at %s/build\n' "$WEBSITE_DIR"
  else
    DISTRIBUTION_ID=""

    aws sts get-caller-identity >/dev/null

    # Terraform state is convenient when it is available, but deployment must
    # not depend on a local state file. The S3 bucket created by this stack is
    # named after the site domain, and CloudFront can be discovered by alias.
    if command -v terraform >/dev/null 2>&1; then
      TERRAFORM_SITE_BUCKET="$(terraform -chdir="$TERRAFORM_DIR" output -raw site_bucket 2>/dev/null || true)"
      if [ -z "${LOKI_SITE_BUCKET:-}" ] && [ -n "$TERRAFORM_SITE_BUCKET" ]; then
        SITE_BUCKET="$TERRAFORM_SITE_BUCKET"
      fi
    fi

    DISTRIBUTION_ID="$(resolve_cloudfront_distribution_id)"

    if [ -z "$SITE_BUCKET" ]; then
      printf '%s\n' 'Could not resolve the Loki site S3 bucket. Set LOKI_SITE_BUCKET or run with --with-infra.' >&2
      exit 1
    fi

    if ! aws s3api head-bucket --bucket "$SITE_BUCKET" >/dev/null 2>&1; then
      printf 'S3 bucket %s was not found or is not accessible. Run `%s --with-infra` or set LOKI_SITE_BUCKET.\n' \
        "$SITE_BUCKET" "$0" >&2
      exit 1
    fi

    if [ -z "$DISTRIBUTION_ID" ] || [ "$DISTRIBUTION_ID" = "None" ]; then
      printf 'CloudFront for %s is still missing. Run `%s --with-infra` to finish the partially-created infrastructure, or set LOKI_CLOUDFRONT_DISTRIBUTION_ID.\n' \
        "$SITE_DOMAIN" "$0" >&2
      exit 1
    fi

    printf 'Uploading site to s3://%s/\n' "$SITE_BUCKET"
    aws s3 sync "$WEBSITE_DIR/build/" "s3://$SITE_BUCKET/" --delete
    printf 'Invalidating CloudFront distribution %s\n' "$DISTRIBUTION_ID"
    aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths '/*' >/dev/null
    printf 'Deployed https://%s\n' "$SITE_DOMAIN"
  fi
fi

printf '\nDeployment workflow completed successfully.\n'
