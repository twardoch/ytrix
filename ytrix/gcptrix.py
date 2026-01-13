#!/usr/bin/env python3
# this_file: gcptrix.py

"""
gcptrix - A tool to clone Google Cloud projects.

Copies project structure, IAM policies, enabled services, and billing
configuration from a source project to a new project with a suffix.
"""

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class GcloudError(Exception):
    """Raised when a gcloud command fails."""

    pass


class AuthenticationError(Exception):
    """Raised when authentication is missing or invalid."""

    pass


def print_section(title: str) -> None:
    """Print a section header."""
    if _quiet:
        return
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_step(step_num: int, description: str) -> None:
    """Print a step indicator."""
    if _quiet:
        return
    print(f"\n[Step {step_num}] {description}")
    print("-" * 40)


def print_success(message: str) -> None:
    """Print a success message."""
    if _quiet:
        return
    print(f"  ✓ {message}")


def print_warning(message: str) -> None:
    """Print a warning message (always shown)."""
    print(f"  ⚠ WARNING: {message}", file=sys.stderr)


def print_error(message: str) -> None:
    """Print an error message (always shown)."""
    print(f"  ✗ ERROR: {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an info message."""
    if _quiet:
        return
    print(f"  → {message}")


def check_gcloud_installed() -> bool:
    """Check if gcloud CLI is installed and accessible."""
    return shutil.which("gcloud") is not None


# Global output control flags
_verbose = False
_quiet = False


def set_verbose(verbose: bool) -> None:
    """Set global verbose mode."""
    global _verbose
    _verbose = verbose


def set_quiet(quiet: bool) -> None:
    """Set global quiet mode (errors only)."""
    global _quiet
    _quiet = quiet


def run_gcloud_command(
    command: list[str], dry_run: bool = False, allow_failure: bool = False
) -> str:
    """
    Run a gcloud command and return the output.

    Args:
        command: The gcloud command as a list of strings.
        dry_run: If True, only print what would be run.
        allow_failure: If True, return empty string on failure instead of raising.

    Returns:
        The stdout from the command.

    Raises:
        GcloudError: If the command fails and allow_failure is False.
    """
    if dry_run:
        print_info(f"Would run: {' '.join(command)}")
        return ""

    if _verbose:
        print_info(f"Running: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        if _verbose and result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line:
                    print_info(f"  {line}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if allow_failure:
            return ""
        error_msg = e.stderr.strip() if e.stderr else "Unknown error"
        raise GcloudError(f"Command failed: {' '.join(command)}\n{error_msg}") from e
    except FileNotFoundError as e:
        raise GcloudError("gcloud CLI not found. Please install the Google Cloud SDK.") from e


def check_authentication() -> dict:
    """
    Check if the user is authenticated with gcloud.

    Returns:
        A dict with authentication status and account info.

    Raises:
        AuthenticationError: If not authenticated.
    """
    # Check active account
    try:
        account = run_gcloud_command(
            ["gcloud", "config", "get-value", "account"], allow_failure=True
        )
    except GcloudError:
        account = ""

    if not account or account == "(unset)":
        raise AuthenticationError("No active gcloud account found.")

    # Check if credentials are valid by making a simple API call
    try:
        run_gcloud_command(
            ["gcloud", "auth", "print-access-token"],
            allow_failure=False,
        )
    except GcloudError as e:
        raise AuthenticationError(
            f"Credentials are invalid or expired for account: {account}"
        ) from e

    return {"account": account, "authenticated": True}


def print_auth_instructions() -> None:
    """Print detailed authentication instructions."""
    print_section("Authentication Required")
    print(
        """
To use this tool, you must authenticate with Google Cloud:

1. INSTALL GCLOUD CLI (if not already installed):

   macOS:    brew install google-cloud-sdk
   Windows:  Download from https://cloud.google.com/sdk/docs/install
   Linux:    curl https://sdk.cloud.google.com | bash

2. AUTHENTICATE YOUR ACCOUNT:

   gcloud auth login

   This opens a browser window for you to sign in with your Google account.
   Choose an account that has permissions on both the source and target projects.

3. SET YOUR DEFAULT PROJECT (optional but recommended):

   gcloud config set project YOUR_PROJECT_ID

4. VERIFY AUTHENTICATION:

   gcloud auth list
   gcloud config get-value account

REQUIRED PERMISSIONS:
  On the SOURCE project, you need:
    - resourcemanager.projects.get
    - resourcemanager.projects.getIamPolicy
    - serviceusage.services.list
    - billing.resourceAssociations.list

  For the NEW project, you need:
    - resourcemanager.projects.create (on the parent folder/organization)
    - resourcemanager.projects.setIamPolicy
    - serviceusage.services.enable
    - billing.resourceAssociations.create

  These are typically granted by roles:
    - roles/owner or roles/editor on the source project
    - roles/resourcemanager.projectCreator on the folder/organization
    - roles/billing.user on the billing account

For more details, see:
  https://cloud.google.com/sdk/docs/authorizing
"""
    )


def check_project_permissions(project_id: str, dry_run: bool = False) -> bool:
    """
    Check if the user has sufficient permissions on the project.

    Returns:
        True if permissions are sufficient.
    """
    if dry_run:
        return True

    try:
        run_gcloud_command(
            ["gcloud", "projects", "describe", project_id, "--format=value(projectId)"]
        )
        return True
    except GcloudError:
        return False


def get_project_info(project_id: str, dry_run: bool = False) -> dict:
    """Get project information including parent."""
    if dry_run:
        return {"projectId": project_id, "parent": None}

    output = run_gcloud_command(["gcloud", "projects", "describe", project_id, "--format=json"])
    return json.loads(output)


def project_exists(project_id: str, dry_run: bool = False) -> bool:
    """Check if a project with the given ID already exists."""
    if dry_run:
        return False

    output = run_gcloud_command(
        [
            "gcloud",
            "projects",
            "list",
            "--filter",
            f"project_id={project_id}",
            "--format=json",
        ]
    )
    projects = json.loads(output)
    return len(projects) > 0


def get_project_labels(project_id: str, dry_run: bool = False) -> dict[str, str]:
    """Get labels from a project."""
    if dry_run:
        return {}

    output = run_gcloud_command(
        ["gcloud", "projects", "describe", project_id, "--format=json(labels)"],
        allow_failure=True,
    )
    if not output:
        return {}
    data = json.loads(output)
    if not data:
        return {}
    return data.get("labels") or {}


def set_project_labels(project_id: str, labels: dict[str, str], dry_run: bool = False) -> None:
    """Set labels on a project."""
    if not labels:
        return

    # Format: key1=value1,key2=value2
    label_str = ",".join(f"{k}={v}" for k, v in labels.items())
    run_gcloud_command(
        ["gcloud", "projects", "update", project_id, f"--update-labels={label_str}"],
        dry_run=dry_run,
    )


def create_project(project_id: str, parent: dict | None, dry_run: bool = False) -> None:
    """Create a new project with optional parent."""
    command = ["gcloud", "projects", "create", project_id]

    if parent:
        if parent["type"] == "folder":
            command.extend(["--folder", parent["id"]])
        elif parent["type"] == "organization":
            command.extend(["--organization", parent["id"]])

    run_gcloud_command(command, dry_run=dry_run)


def get_billing_info(project_id: str, dry_run: bool = False) -> dict:
    """Get billing information for a project."""
    if dry_run:
        return {}

    output = run_gcloud_command(
        ["gcloud", "billing", "projects", "describe", project_id, "--format=json"]
    )
    return json.loads(output)


def link_billing(project_id: str, billing_account_id: str, dry_run: bool = False) -> None:
    """Link a project to a billing account."""
    run_gcloud_command(
        [
            "gcloud",
            "billing",
            "projects",
            "link",
            project_id,
            "--billing-account",
            billing_account_id,
        ],
        dry_run=dry_run,
    )


def get_iam_policy(project_id: str, dry_run: bool = False) -> str:
    """Get the IAM policy for a project as JSON string."""
    if dry_run:
        return "{}"

    return run_gcloud_command(["gcloud", "projects", "get-iam-policy", project_id, "--format=json"])


def set_iam_policy(project_id: str, policy_file: str, dry_run: bool = False) -> None:
    """Set the IAM policy for a project from a JSON file."""
    run_gcloud_command(
        ["gcloud", "projects", "set-iam-policy", project_id, policy_file],
        dry_run=dry_run,
    )


def get_enabled_services(project_id: str, dry_run: bool = False) -> list[str]:
    """Get list of enabled services for a project."""
    if dry_run:
        return []

    output = run_gcloud_command(
        ["gcloud", "services", "list", "--project", project_id, "--format=json"]
    )
    services = json.loads(output)
    return [s["config"]["name"] for s in services if s["state"] == "ENABLED"]


def run_inventory(project_id: str) -> int:
    """Show inventory of resources in a project."""
    print_section(f"Project Inventory: {project_id}")

    # Check authentication first
    try:
        auth_info = check_authentication()
        print_info(f"Authenticated as: {auth_info['account']}")
    except AuthenticationError as e:
        print_error(str(e))
        return 1

    # Check project access
    if not check_project_permissions(project_id):
        print_error(f"Cannot access project: {project_id}")
        return 1

    # Track counts for summary
    label_count = 0
    sa_count = 0
    custom_sa_count = 0
    service_count = 0
    has_billing = False

    # Get project info
    print(f"\n{'─' * 50}")
    print("  PROJECT INFO")
    print(f"{'─' * 50}")
    try:
        info = get_project_info(project_id)
        print(f"  Project ID:     {info.get('projectId', 'N/A')}")
        print(f"  Project Number: {info.get('projectNumber', 'N/A')}")
        print(f"  Name:           {info.get('name', 'N/A')}")
        parent = info.get("parent")
        if parent:
            print(f"  Parent:         {parent.get('type', '')} ({parent.get('id', '')})")
    except GcloudError as e:
        print_warning(f"Could not get project info: {e}")

    # Get labels
    print(f"\n{'─' * 50}")
    print("  LABELS")
    print(f"{'─' * 50}")
    try:
        labels = get_project_labels(project_id)
        label_count = len(labels)
        if labels:
            for k, v in labels.items():
                print(f"  {k}: {v}")
        else:
            print("  (none)")
    except GcloudError as e:
        print_warning(f"Could not get labels: {e}")

    # Get billing
    print(f"\n{'─' * 50}")
    print("  BILLING")
    print(f"{'─' * 50}")
    try:
        billing = get_billing_info(project_id)
        if billing.get("billingEnabled"):
            has_billing = True
            account = billing.get("billingAccountName", "").split("/")[-1]
            print(f"  Billing Account: {account}")
        else:
            print("  Billing: Not enabled")
    except GcloudError as e:
        print_warning(f"Could not get billing: {e}")

    # Get service accounts
    print(f"\n{'─' * 50}")
    print("  SERVICE ACCOUNTS")
    print(f"{'─' * 50}")
    default_patterns = [
        "-compute@developer",
        "@cloudservices",
        "@cloudbuild",
        "@appspot",
        "firebase-adminsdk",
    ]
    try:
        sas = get_service_accounts(project_id)
        sa_count = len(sas)
        if sas:
            for sa in sas:
                email = sa.get("email", "N/A")
                is_custom = email.endswith(".iam.gserviceaccount.com") and not any(
                    p in email for p in default_patterns
                )
                if is_custom:
                    custom_sa_count += 1
                    print(f"  {email} [clonable]")
                else:
                    print(f"  {email} [managed]")
            print(f"  Total: {sa_count} ({custom_sa_count} clonable)")
        else:
            print("  (none)")
    except GcloudError as e:
        print_warning(f"Could not get service accounts: {e}")

    # Get enabled services
    print(f"\n{'─' * 50}")
    print("  ENABLED SERVICES")
    print(f"{'─' * 50}")
    try:
        services = get_enabled_services(project_id)
        service_count = len(services)
        if services:
            for svc in sorted(services):
                print(f"  {svc}")
            print(f"  Total: {service_count}")
        else:
            print("  (none)")
    except GcloudError as e:
        print_warning(f"Could not get services: {e}")

    # Cloning summary
    print(f"\n{'─' * 50}")
    print("  CLONING SUMMARY")
    print(f"{'─' * 50}")
    print("  Resource              Count   Clonable")
    print("  ────────────────────  ─────   ────────")
    print("  Project structure     1       ✓ Yes")
    print(f"  Labels                {label_count:<5}   ✓ Yes")
    print("  IAM policies          1       ✓ Yes")
    print(f"  Service accounts      {custom_sa_count:<5}   ✓ Yes (custom only)")
    print(f"  Enabled services      {service_count:<5}   ✓ Yes")
    print(f"  Billing linkage       {'1' if has_billing else '0':<5}   ✓ Yes")
    print()
    print("  Not clonable (manual setup required):")
    print("    - SA keys, OAuth credentials, secrets")
    print("    - Cloud Storage, BigQuery, Firestore data")
    print("    - Cloud Functions/Run deployments")
    print("    - VPC networks, Compute Engine resources")

    print(f"\n{'─' * 50}")
    print(f"  Console: https://console.cloud.google.com/home/dashboard?project={project_id}")
    print(f"{'─' * 50}")

    return 0


def enable_service(project_id: str, service: str, dry_run: bool = False) -> None:
    """Enable a service on a project."""
    run_gcloud_command(
        ["gcloud", "services", "enable", service, "--project", project_id],
        dry_run=dry_run,
    )


def get_service_accounts(project_id: str, dry_run: bool = False) -> list[dict]:
    """Get list of service accounts in a project."""
    if dry_run:
        return []

    output = run_gcloud_command(
        ["gcloud", "iam", "service-accounts", "list", "--project", project_id, "--format=json"]
    )
    return json.loads(output) if output else []


def create_service_account(
    project_id: str, account_id: str, display_name: str, dry_run: bool = False
) -> None:
    """Create a service account in a project."""
    run_gcloud_command(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "create",
            account_id,
            "--project",
            project_id,
            "--display-name",
            display_name,
        ],
        dry_run=dry_run,
    )


def get_service_account_iam(project_id: str, sa_email: str, dry_run: bool = False) -> list[dict]:
    """Get IAM bindings for a service account."""
    if dry_run:
        return []

    output = run_gcloud_command(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "get-iam-policy",
            sa_email,
            "--project",
            project_id,
            "--format=json",
        ],
        allow_failure=True,
    )
    if not output:
        return []
    policy = json.loads(output)
    return policy.get("bindings", [])


def print_manual_steps(source_project: str, new_project: str) -> None:
    """Print detailed manual steps required after cloning."""
    print_section("Manual Steps Required")
    print(
        f"""
The automated cloning is complete, but the following items require manual action:

1. SERVICE ACCOUNTS
   Service accounts are NOT copied. To recreate them:

   # List service accounts in source project:
   gcloud iam service-accounts list --project={source_project}

   # Create each service account in new project:
   gcloud iam service-accounts create SERVICE_ACCOUNT_NAME \\
       --project={new_project} \\
       --display-name="DISPLAY_NAME"

   # Grant roles to service account:
   gcloud projects add-iam-policy-binding {new_project} \\
       --member="serviceAccount:SA_EMAIL" \\
       --role="ROLE_NAME"

2. SERVICE ACCOUNT KEYS
   Keys must be regenerated (they cannot be copied):

   gcloud iam service-accounts keys create key.json \\
       --iam-account=SA_EMAIL

3. OAUTH CONSENT SCREEN
   If your project uses OAuth, configure the consent screen:

   Visit: https://console.cloud.google.com/apis/credentials/consent?project={new_project}

4. API CREDENTIALS
   OAuth client IDs and API keys must be recreated:

   Visit: https://console.cloud.google.com/apis/credentials?project={new_project}

5. CLOUD STORAGE
   Buckets and their contents are NOT copied. To copy:

   # List buckets in source:
   gsutil ls -p {source_project}

   # Copy bucket contents:
   gsutil -m cp -r gs://SOURCE_BUCKET/* gs://NEW_BUCKET/

6. BIGQUERY DATASETS
   Datasets and tables are NOT copied. To copy:

   # List datasets:
   bq ls --project_id={source_project}

   # Copy dataset:
   bq mk --transfer_config --project_id={new_project} \\
       --data_source=cross_region_copy \\
       --target_dataset=DATASET_NAME \\
       --params='source_project_id={source_project},source_dataset_id=DATASET_NAME'

7. CLOUD FUNCTIONS / CLOUD RUN
   These must be redeployed from source code.

8. FIRESTORE / DATASTORE
   Data must be exported and imported:

   # Export from source:
   gcloud firestore export gs://BUCKET_NAME --project={source_project}

   # Import to new project:
   gcloud firestore import gs://BUCKET_NAME --project={new_project}

9. SECRETS (Secret Manager)
   Secrets must be recreated manually:

   # List secrets:
   gcloud secrets list --project={source_project}

   # Create secret in new project:
   gcloud secrets create SECRET_NAME --project={new_project}

   # Add secret version:
   echo "SECRET_VALUE" | gcloud secrets versions add SECRET_NAME \\
       --project={new_project} --data-file=-

10. VPC NETWORKS
    Custom VPC networks and firewall rules must be recreated.

11. COMPUTE ENGINE
    VM instances, disks, and images are NOT copied.

For a complete list of resources in your source project, visit:
  https://console.cloud.google.com/home/dashboard?project={source_project}

New project console:
  https://console.cloud.google.com/home/dashboard?project={new_project}
"""
    )


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Clone a Google Cloud project or show project inventory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s my-project clone1
      Creates 'my-project-clone1' as a copy of 'my-project'

  %(prog)s my-project backup --dry-run
      Shows what would be done without making changes

  %(prog)s --inventory my-project
      Shows inventory of resources in the project

Authentication:
  Run 'gcloud auth login' before using this tool.
  See --help-auth for detailed authentication instructions.
        """,
    )
    parser.add_argument("source_project", nargs="?", help="The source project ID.")
    parser.add_argument(
        "new_project_suffix",
        nargs="?",
        help="The suffix for the new project (creates SOURCE-SUFFIX).",
    )
    parser.add_argument(
        "--inventory",
        "-i",
        action="store_true",
        help="Show inventory of resources in source project (no cloning).",
    )
    parser.add_argument(
        "--new-project", help="Full project ID for the new project (overrides suffix)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what will be done without making changes.",
    )
    parser.add_argument(
        "--help-auth",
        action="store_true",
        help="Show detailed authentication instructions.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output including gcloud commands.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Show only errors and warnings (minimal output).",
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Skip copying project labels.",
    )
    parser.add_argument(
        "--skip-service-accounts",
        action="store_true",
        help="Skip cloning service accounts.",
    )
    parser.add_argument(
        "--exclude-services",
        help="Comma-separated services to skip (e.g., 'bigquery.googleapis.com').",
    )

    args = parser.parse_args()

    # Set output modes (quiet takes precedence over verbose)
    if args.quiet:
        set_quiet(True)
    elif args.verbose:
        set_verbose(True)

    # Handle --help-auth
    if args.help_auth:
        print_auth_instructions()
        return 0

    # Require source project
    if not args.source_project:
        parser.print_help()
        return 1

    source_project_id = args.source_project

    # Handle --inventory mode
    if args.inventory:
        return run_inventory(source_project_id)

    # For cloning, require suffix or --new-project
    if not args.new_project_suffix and not args.new_project:
        print_error("Must specify either NEW_PROJECT_SUFFIX or --new-project (or use --inventory)")
        parser.print_help()
        return 1

    # Use --new-project if provided, otherwise construct from suffix
    new_project_id = args.new_project or f"{source_project_id}-{args.new_project_suffix}"
    dry_run = args.dry_run

    print_section("Google Cloud Project Cloner")
    print(f"  Source project: {source_project_id}")
    print(f"  New project:    {new_project_id}")

    if dry_run:
        print("\n  *** DRY RUN MODE - No changes will be made ***")

    # Step 0: Check prerequisites
    print_step(0, "Checking prerequisites")

    if not check_gcloud_installed():
        print_error("gcloud CLI is not installed or not in PATH.")
        print_info("Install from: https://cloud.google.com/sdk/docs/install")
        print_info("Or run: brew install google-cloud-sdk (macOS)")
        return 1
    print_success("gcloud CLI is installed")

    # Step 1: Check authentication
    print_step(1, "Checking authentication")

    try:
        auth_info = check_authentication()
        print_success(f"Authenticated as: {auth_info['account']}")
    except AuthenticationError as e:
        print_error(str(e))
        print_info("Run 'gcloud auth login' to authenticate")
        print_info("Or run this tool with --help-auth for detailed instructions")
        return 1

    # Step 2: Verify source project access
    print_step(2, "Verifying source project access")

    if not check_project_permissions(source_project_id, dry_run):
        print_error(f"Cannot access project: {source_project_id}")
        print_info("Check that the project ID is correct")
        print_info("Verify you have 'resourcemanager.projects.get' permission")
        return 1
    print_success(f"Can access source project: {source_project_id}")

    # Step 3: Check if new project already exists
    print_step(3, "Checking if new project already exists")

    if project_exists(new_project_id, dry_run):
        print_error(f"Project already exists: {new_project_id}")
        print_info("Choose a different suffix or delete the existing project")
        return 1
    print_success(f"Project ID is available: {new_project_id}")

    # Step 4: Get source project info
    print_step(4, "Getting source project information")

    try:
        project_info = get_project_info(source_project_id, dry_run)
        parent = project_info.get("parent")
        if parent:
            print_info(f"Parent: {parent['type']} ({parent['id']})")
        else:
            print_info("No parent organization/folder")
            parent = None
    except GcloudError as e:
        print_error(f"Failed to get project info: {e}")
        return 1

    # Step 5: Create new project
    print_step(5, "Creating new project")

    try:
        create_project(new_project_id, parent, dry_run)
        if not dry_run:
            print_success(f"Created project: {new_project_id}")
    except GcloudError as e:
        print_error(f"Failed to create project: {e}")
        print_info("Ensure you have 'resourcemanager.projects.create' permission")
        if parent:
            print_info(f"on the {parent['type']}: {parent['id']}")
        return 1

    # Step 6: Copy labels
    if not args.skip_labels:
        print_step(6, "Copying project labels")

        try:
            labels = get_project_labels(source_project_id, dry_run)
            if labels:
                print_info(f"Found {len(labels)} labels to copy")
                set_project_labels(new_project_id, labels, dry_run)
                if not dry_run:
                    print_success("Labels copied")
            else:
                print_info("No labels to copy")
        except GcloudError as e:
            print_warning(f"Could not copy labels: {e}")
    else:
        print_step(6, "Skipping labels (--skip-labels)")

    # Step 7: Handle billing
    print_step(7, "Configuring billing")

    try:
        billing_info = get_billing_info(source_project_id, dry_run)
        if billing_info.get("billingEnabled"):
            billing_account_name = billing_info.get("billingAccountName", "")
            if billing_account_name:
                billing_account_id = billing_account_name.split("/")[-1]
                print_info(f"Source billing account: {billing_account_id}")
                link_billing(new_project_id, billing_account_id, dry_run)
                if not dry_run:
                    print_success("Linked to billing account")
            else:
                print_warning("Could not determine billing account")
        else:
            print_info("Source project has no billing enabled")
    except GcloudError as e:
        print_warning(f"Could not configure billing: {e}")
        print_info("You may need to link billing manually")

    # Step 7: Copy IAM policy
    print_step(8, "Copying IAM policy")

    # Use a temp file for the IAM policy
    temp_dir = tempfile.mkdtemp(prefix="gcptrix_")
    iam_policy_path = Path(temp_dir) / "iam_policy.json"

    try:
        iam_policy = get_iam_policy(source_project_id, dry_run)
        if not dry_run:
            iam_policy_path.write_text(iam_policy)
            print_info(f"IAM policy saved to: {iam_policy_path}")

        set_iam_policy(new_project_id, str(iam_policy_path), dry_run)
        if not dry_run:
            print_success("IAM policy applied")
    except GcloudError as e:
        print_warning(f"Could not copy IAM policy: {e}")
        print_info("You may need to configure IAM manually")
    finally:
        # Clean up temp files
        if not dry_run and temp_dir:
            with contextlib.suppress(OSError):
                shutil.rmtree(temp_dir)

    # Step 9: Clone service accounts
    if not args.skip_service_accounts:
        print_step(9, "Cloning service accounts")

        try:
            service_accounts = get_service_accounts(source_project_id, dry_run)
            # Filter out default/managed service accounts
            # Keep only custom SAs: those ending in .iam.gserviceaccount.com
            # but NOT containing default patterns (compute, cloudservices, cloudbuild, appspot)
            default_patterns = [
                "-compute@developer",
                "@cloudservices",
                "@cloudbuild",
                "@appspot",
                "firebase-adminsdk",
            ]
            custom_sas = [
                sa
                for sa in service_accounts
                if sa.get("email", "").endswith(".iam.gserviceaccount.com")
                and not any(pattern in sa.get("email", "") for pattern in default_patterns)
            ]
            if custom_sas:
                print_info(f"Found {len(custom_sas)} service accounts to clone")
                for i, sa in enumerate(custom_sas, 1):
                    email = sa.get("email", "")
                    display_name = sa.get("displayName", email.split("@")[0])
                    # Extract account ID from email (before @)
                    account_id = email.split("@")[0] if email else f"sa-{i}"
                    print_info(f"  [{i}/{len(custom_sas)}] Creating {account_id}...")
                    try:
                        create_service_account(new_project_id, account_id, display_name, dry_run)
                    except GcloudError as e:
                        print_warning(f"Could not create {account_id}: {e}")
                if not dry_run:
                    print_success("Service accounts created (keys must be generated manually)")
            else:
                print_info("No custom service accounts to clone")
        except GcloudError as e:
            print_warning(f"Could not list service accounts: {e}")
    else:
        print_step(9, "Skipping service accounts (--skip-service-accounts)")

    # Step 10: Copy enabled services
    print_step(10, "Enabling services")

    # Parse excluded services
    excluded_services = set()
    if args.exclude_services:
        excluded_services = {s.strip() for s in args.exclude_services.split(",")}
        print_info(f"Excluding {len(excluded_services)} services: {', '.join(excluded_services)}")

    try:
        services = get_enabled_services(source_project_id, dry_run)
        # Filter out excluded services
        services_to_enable = [s for s in services if s not in excluded_services]
        skipped_count = len(services) - len(services_to_enable)

        if services_to_enable:
            print_info(
                f"Found {len(services_to_enable)} services to enable"
                + (f" ({skipped_count} excluded)" if skipped_count else "")
            )
            for i, service in enumerate(services_to_enable, 1):
                print_info(f"  [{i}/{len(services_to_enable)}] Enabling {service}...")
                try:
                    enable_service(new_project_id, service, dry_run)
                except GcloudError as e:
                    print_warning(f"Could not enable {service}: {e}")
            if not dry_run:
                print_success("Services enabled")
        else:
            print_info("No services to enable")
    except GcloudError as e:
        print_warning(f"Could not list services: {e}")

    # Final summary
    if dry_run:
        print_section("Dry Run Complete")
        print("  No changes were made. Remove --dry-run to execute.")
    else:
        print_section("Automated Cloning Complete")
        print(f"  New project created: {new_project_id}")
        print(
            f"  Console: https://console.cloud.google.com/home/dashboard?project={new_project_id}"
        )

    # Print manual steps
    print_manual_steps(source_project_id, new_project_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
