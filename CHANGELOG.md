# Viralizer Video Studio changelog

## v1.1.0-beta.11 — 2026-08-21 — Private testing

- Removed Opinion, Editorial, Analysis, Commentary, Review, Explainer and Deep Dive prefixes from search terms.
- Preserved specific event words such as backlash and criticism.
- Removed generic “explained” alternates from issue searches.
- The supplied example becomes “Cancer vaccine technology backlash.”

## v1.1.0-beta.10 — 2026-08-21 — Private testing

- Fixed incomplete search phrases generated from How, Why and similar editorial headlines.
- Removed grammatical filler including in, of, age and becomes.
- Normalized Artificial Intelligence to AI in concise searches.
- The supplied example now becomes “Code AI Write-Only Disposable.”

## v1.1.0-beta.9 — 2026-08-21 — Private testing

- Removed the repetitive “latest update” fallback from concise topic searches.
- Search terms now combine the detected entity with meaningful headline keywords.
- Search terms remain five words or fewer.
- Generic “explained” alternates are no longer added when the headline is already specific.

## v1.1.0-beta.8 — 2026-08-21 — Private testing

- Replaced Type: Everything with an automatically detected result type.
- Added Company / Brand, Product, Person / Celebrity, App / Software, Government, Country / Region, Organization, Event, Movie / TV show and General topic labels.
- A specific entity-type dropdown selection remains authoritative.

## v1.1.0-beta.7 — 2026-08-21 — Private testing

- Fixed weather “watches” being classified as Fashion > Watches.
- Fixed “issued” incorrectly triggering the negative word “sued.”
- Broad searches now remove results without evidence for any selected category.
- Entity Type now displays the selected dropdown value, including Everything.

## v1.1.0-beta.6 — 2026-08-21 — Private testing

- Added Category, Entity and Entity type labels to worldwide topic cards.
- All-category results are matched to the most relevant selected category.
- Focused category and subcategory results keep their exact selected label.
- Extended view explains whether the category came from a keyword match or general fallback.

## v1.1.0-beta.5 — 2026-08-21 — Private testing

- Added Good news, Bad news, Mixed / debate and Neutral labels to worldwide category topic cards.
- Added color coding for faster scanning.
- Extended view explains which headline or summary signals produced the automated label.
- Labels do not hide, remove or rerank results.

## v1.1.0-beta.4 — 2026-08-21 — Private testing

- Added a simple **Update production** button to publish the approved beta.
- Added a **Rollback production** button beside the detailed impact preview.
- Both actions require administrator authentication and an exact typed confirmation.
- Controls remain locked until `GITHUB_DEPLOY_TOKEN` is configured in the private beta service.

## v1.1.0-beta.3 — 2026-08-19 — Private testing

- Added “All categories” to Category Intelligence.
- Selecting it searches every category belonging to the chosen super category.
- Category names are batched into efficient worldwide searches, with loading progress and combined freshness-ranked results.
- Selecting one category or subcategory continues to use the existing focused search.

## v1.1.0-beta.2 — 2026-08-17 — Private testing

- Changed beta to Render's free service plan.
- Removed the beta persistent disk requirement.
- Beta reports use temporary storage and can disappear after a service restart.
- Production storage and production users are unaffected.

## v1.1.0-beta.1 — 2026-08-17 — Private testing

### Added

- Separate administrator authentication using `ADMIN_PASSWORD`.
- Private release dashboard at `/admin`.
- Detailed version history with before-and-after explanations.
- Version comparison across files, endpoints, configuration names, data impact and tests.
- Rollback impact preview that does not change production.
- Separate Render beta blueprint targeting the `develop` branch.

### Safety

- Production publishing and rollback execution remain locked.
- The dashboard is not visible to regular users without the separate administrator password.
- The existing `main` branch remains the production branch.

## v1.0.0 — 2026-08-16 — Production baseline

- Added dated extended-news details and original-source links.
- Sorted Category Intelligence topics by freshness.
- Expanded good and bad reputation discovery queries.
- Added five-word entity-led YouTube search terms.
- Added full-content infographic generation.
- Added actual uploaded-image reference generation.

The complete change-by-change record is stored in `data/release_catalog.json` and displayed in the private dashboard.
