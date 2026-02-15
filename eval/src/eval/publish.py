"""Publish campaign results to the operator-campaigns repo.

Automates: behavior classification, HTML export, source code capture
as an orphan branch, README generation, and push.
"""

import logging
import os
import re
import subprocess
from pathlib import Path

from eval.types import Campaign, parse_iso_datetime

logger = logging.getLogger(__name__)

# Subjects with browsable source code (CodeWorkspace-based subjects)
SUBJECT_SOURCE_PATHS = {
    "chat-db-app": "subjects/chat-db-app/service",
}

GITHUB_REPO = "pikehouse/operator-campaigns"


def _git(repo: Path, *args: str) -> str:
    """Run a git command in the given repo directory.

    Returns stdout on success, raises on failure.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def get_results_repo_path() -> Path:
    """Read OPERATOR_RESULTS_REPO_LOCATION from env and validate."""
    raw = os.environ.get("OPERATOR_RESULTS_REPO_LOCATION")
    if not raw:
        raise RuntimeError(
            "OPERATOR_RESULTS_REPO_LOCATION not set. "
            "Add it to your .env file (e.g. ~/x/operator-campaigns)"
        )
    repo = Path(raw).expanduser()
    if not repo.is_dir():
        raise RuntimeError(f"Results repo not found: {repo}")
    git_dir = repo / ".git"
    if not git_dir.exists():
        raise RuntimeError(f"Not a git repo: {repo}")
    return repo


def get_operator_repo_root() -> Path:
    """Get the operator repo root via git or fallback."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except FileNotFoundError:
        pass
    return Path(__file__).parents[3]


def campaign_filename(campaign: Campaign) -> str:
    """Generate HTML filename from campaign created_at timestamp.

    Format: {YYYY-MM-DD-HHMM}-campaign-{ID}.html
    """
    dt = parse_iso_datetime(campaign.created_at)
    if dt is None:
        raise ValueError(f"Campaign {campaign.id} has no created_at timestamp")
    return f"{dt.strftime('%Y-%m-%d-%H%M')}-campaign-{campaign.id}.html"


def find_existing_html(results_repo: Path, campaign_id: int) -> Path | None:
    """Find an existing HTML export for this campaign (for re-publish)."""
    pattern = f"*-campaign-{campaign_id}.html"
    matches = list(results_repo.glob(pattern))
    return matches[0] if matches else None


def publish_html(
    results_repo: Path, campaign: Campaign, html_content: str
) -> tuple[Path, bool]:
    """Write HTML file to results repo and stage it.

    Returns (path, is_update) — is_update=True if re-publishing.
    """
    existing = find_existing_html(results_repo, campaign.id)
    if existing:
        html_path = existing
        is_update = True
    else:
        html_path = results_repo / campaign_filename(campaign)
        is_update = False

    html_path.write_text(html_content)
    _git(results_repo, "add", html_path.name)
    return html_path, is_update


def publish_source_branch(
    results_repo: Path, operator_repo: Path, campaign: Campaign
) -> str | None:
    """Create an orphan branch with the subject's source code at the campaign's commit.

    Returns branch name on success, None if skipped.
    """
    source_path = SUBJECT_SOURCE_PATHS.get(campaign.subject_name)
    if not source_path:
        logger.info(
            "No source path configured for subject %r, skipping source branch",
            campaign.subject_name,
        )
        return None

    commit = campaign.git_commit_hash
    if not commit:
        logger.warning(
            "Campaign %d has no git_commit_hash, skipping source branch",
            campaign.id,
        )
        return None

    # Validate commit exists in operator repo
    try:
        _git(operator_repo, "cat-file", "-e", commit)
    except RuntimeError:
        logger.warning(
            "Commit %s not found in operator repo, skipping source branch",
            commit,
        )
        return None

    branch_name = f"campaign-{campaign.id}-source"

    # Save current branch to restore later
    original_ref = _git(results_repo, "symbolic-ref", "--short", "HEAD")

    try:
        # Delete existing branch if re-publishing
        try:
            _git(results_repo, "rev-parse", "--verify", branch_name)
            # Branch exists — delete it
            _git(results_repo, "branch", "-D", branch_name)
        except RuntimeError:
            pass  # Branch doesn't exist, that's fine

        # Create orphan branch
        _git(results_repo, "checkout", "--orphan", branch_name)

        # Remove all tracked files from index
        _git(results_repo, "rm", "-rf", "--quiet", ".")

        # Extract source at the specific commit using git archive + tar
        archive_proc = subprocess.run(
            ["git", "archive", commit, "--", source_path],
            cwd=operator_repo,
            capture_output=True,
        )
        if archive_proc.returncode != 0:
            raise RuntimeError(
                f"git archive failed: {archive_proc.stderr.decode().strip()}"
            )

        # Extract tar, flattening the source_path prefix so root = service dir contents
        tar_proc = subprocess.run(
            ["tar", "xf", "-", "--strip-components", str(source_path.count("/") + 1)],
            cwd=results_repo,
            input=archive_proc.stdout,
            capture_output=True,
        )
        if tar_proc.returncode != 0:
            raise RuntimeError(
                f"tar extract failed: {tar_proc.stderr.decode().strip()}"
            )

        # Stage and commit
        _git(results_repo, "add", "-A")
        _git(
            results_repo,
            "commit",
            "-m",
            f"Source for campaign {campaign.id} ({campaign.subject_name} @ {commit[:8]})",
        )

        return branch_name

    finally:
        # Always restore original branch
        try:
            _git(results_repo, "checkout", original_ref)
        except RuntimeError:
            # Fallback: try main
            try:
                _git(results_repo, "checkout", "main")
            except RuntimeError:
                logger.error("Failed to restore branch in results repo!")


def _preview_url(filename: str) -> str:
    """Generate an htmlpreview.github.io URL for a file."""
    return (
        f"https://htmlpreview.github.io/?"
        f"https://github.com/{GITHUB_REPO}/blob/main/{filename}"
    )


def _source_url(branch_name: str) -> str:
    """Generate a GitHub tree URL for a source branch."""
    return f"https://github.com/{GITHUB_REPO}/tree/{branch_name}"


def generate_readme(results_repo: Path) -> str:
    """Generate README.md content by scanning HTML files and source branches."""
    # Get list of all source branches
    branch_output = _git(results_repo, "branch", "--list", "campaign-*-source")
    source_branches = set()
    for line in branch_output.splitlines():
        branch = line.strip().lstrip("* ")
        if branch:
            source_branches.add(branch)

    # Scan HTML files
    html_files = sorted(results_repo.glob("*-campaign-*.html"), reverse=True)

    rows = []
    for html_path in html_files:
        # Extract campaign ID from filename
        m = re.search(r"-campaign-(\d+)\.html$", html_path.name)
        if not m:
            continue
        cid = m.group(1)

        # Extract date from filename (YYYY-MM-DD)
        date_m = re.match(r"(\d{4}-\d{2}-\d{2})", html_path.name)
        date_str = date_m.group(1) if date_m else "unknown"

        preview = _preview_url(html_path.name)
        branch = f"campaign-{cid}-source"
        source = f"[Browse Source]({_source_url(branch)})" if branch in source_branches else "-"

        rows.append(f"| {cid} | {date_str} | [View Report]({preview}) | {source} |")

    table = "\n".join(rows) if rows else "| (none) | | | |"

    return f"""# Operator Campaign Results

| Campaign | Date | Report | Source |
|----------|------|--------|--------|
{table}
"""


def update_readme(results_repo: Path) -> None:
    """Regenerate README.md and stage it."""
    readme_path = results_repo / "README.md"
    readme_path.write_text(generate_readme(results_repo))
    _git(results_repo, "add", "README.md")


async def publish_campaign(
    db,
    campaign_id: int,
    *,
    skip_behavior: bool = False,
    force_behavior: bool = False,
    skip_source: bool = False,
    dry_run: bool = False,
) -> dict:
    """Publish a campaign to the results repo.

    Steps:
    1. Validate config (results repo, operator repo)
    2. Fetch campaign
    3. Classify behavior (unless --skip-behavior)
    4. Export HTML
    5. Write HTML to results repo
    6. Create orphan source branch (unless --skip-source)
    7. Regenerate README
    8. Commit and push (unless --dry-run)

    Returns dict with publish results.
    """
    from eval.analysis.behavior import classify_campaign_behavior
    from eval.export import export_campaign_html

    # 1. Validate config — fail fast
    results_repo = get_results_repo_path()
    operator_repo = get_operator_repo_root()

    # Make sure results repo is on main and clean
    _git(results_repo, "checkout", "main")
    _git(results_repo, "pull")

    # 2. Fetch campaign
    campaign = await db.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    # 3. Behavior classification
    if not skip_behavior:
        logger.info("Classifying behavior for campaign %d...", campaign_id)
        await classify_campaign_behavior(db, campaign_id, force=force_behavior)

    # 4. Export HTML (generate content before any branch switching)
    logger.info("Exporting HTML for campaign %d...", campaign_id)
    html_content = await export_campaign_html(db, campaign_id)

    # 5. Source branch (do BEFORE writing files — orphan branch checkout wipes working tree)
    source_branch = None
    source_url = None
    if not skip_source:
        try:
            source_branch = publish_source_branch(
                results_repo, operator_repo, campaign
            )
            if source_branch:
                source_url = _source_url(source_branch)
        except Exception as e:
            logger.warning("Source branch failed (non-fatal): %s", e)

    # 6. Publish HTML (after source branch, so working tree is back on main)
    html_path, is_update = publish_html(results_repo, campaign, html_content)

    # 7. README
    update_readme(results_repo)

    # 8. Commit (skip if nothing changed)
    verb = "Update" if is_update else "Add"
    has_changes = _git(results_repo, "status", "--porcelain").strip() != ""
    if has_changes:
        _git(results_repo, "commit", "-m", f"{verb} campaign {campaign_id} export")

    # 9. Push
    preview = _preview_url(html_path.name)
    if not dry_run:
        if has_changes:
            _git(results_repo, "push", "origin", "main")
        if source_branch:
            _git(results_repo, "push", "origin", source_branch, "--force")

    return {
        "html_file": html_path.name,
        "preview_url": preview,
        "source_branch": source_branch,
        "source_url": source_url,
        "is_update": is_update,
        "dry_run": dry_run,
    }
