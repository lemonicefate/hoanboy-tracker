# Issue tracker: GitHub

Issues and specs live in https://github.com/lemonicefate/hoanboy-tracker/issues.
Use `gh` with explicit `--repo lemonicefate/hoanboy-tracker` for issue operations.

## Workflow

- Before publishing, confirm authentication and repository access; check existing issues for duplicates.
- Create: `gh issue create --repo lemonicefate/hoanboy-tracker --title "..." --body-file <file> --label <label>`.
- Read: `gh issue view <number> --repo lemonicefate/hoanboy-tracker --comments`; inspect labels as needed.
- List: `gh issue list --repo lemonicefate/hoanboy-tracker --state open --json number,title,body,labels`.
- Apply labels: `gh issue edit <number> --repo lemonicefate/hoanboy-tracker --add-label <label>`; use `--remove-label` to remove.
- Comment: `gh issue comment <number> --repo lemonicefate/hoanboy-tracker --body-file <file>`.
- Close: `gh issue close <number> --repo lemonicefate/hoanboy-tracker`.
- For multiline content, write exact text to a file and use `--body-file`.
- After publishing, read back the issue body and labels and record its URL in the local spec.

“Publish to the issue tracker” means create a GitHub issue. “Fetch the relevant ticket” means read its body, labels and comments.
Keep patient records, images, private report links and credentials out of issue content.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding

Use one `wayfinder:map` issue and linked child issues labelled `wayfinder:<type>`.
Prefer native sub-issues and issue dependencies; if unavailable, use a parent task list, a `Part of #<map>` child reference and `Blocked by: #<n>` references.
Only claim children with no open blocker or assignee; assign the driving developer. On completion, record the outcome, close the child and update the map.
