# Ground Truth annotations

G5-B4 has placed eight **unfrozen P1 draft** JSON documents here: six Autonomous and two Memo. Four `SELECTED` Memo documents, all VLM/Event GT, and later Project GT remain pending. The adjacent review notes record filmmaker confirmations and select `P1-S03-take02`; `take01` is archival. Draft `PASS` means structural/reference validity only, not human GT approval or freeze. Raw media, audio, personal frames, and contact sheets belong only in ignored local evaluation areas.

Task documents use the adjacent `schema/` contracts. Source-level Memo, Autonomous, and VLM documents reference `common.schema.json`; project-level Event documents list common source envelopes for every participating SourceVideo.

Run the media-free G5-B5 validator from the repository root:

```powershell
.\.venv\Scripts\python.exe evaluation\validate_focused_gt.py --mode draft
.\.venv\Scripts\python.exe evaluation\validate_focused_gt.py --mode freeze-ready
```

`draft` validates present JSON only. `freeze-ready` also reports missing planned source envelopes, `COVERED` task GT, and Project Event GT. `CONDITIONAL`/`OPTIONAL` coverage is not forcibly promoted to a required GT case. `FAIL` is a contract violation (exit 1), `PENDING` is an unavailable GT/reference (exit 2), and `PASS` means checks available to this validator succeeded (exit 0). No mode reads media, runs a proposal generator, or freezes GT.

For a future `SELECTED` Memo/VLM document, the validator needs the **already generated** Proposal manifest fingerprint and IDs for reference checking. Without them it reports `PENDING`; it never makes up Proposal IDs. A caller may provide an evaluator-only `--proposal-index` JSON object mapping each real manifest fingerprint to its existing Proposal ID list. This index is not a GT schema and must be prepared and frozen before Provider execution. A supplied index with missing fingerprint or ID is `FAIL`.

`P1-S03-take02` is checked against the explicit selection in `P1-G5-B4-review-notes.md`; this is a v0.1-specific reference check, not a general rule that filenames determine GT. Hashes are checked for syntax and consistency across JSON documents, **not** against absent media bytes. Event direction can be checked against a matching preregistered `CONTINUATION`/`REACTION_TO` intent; the validator cannot infer semantic truth or visual sufficiency from IDs. The existing schema has no machine-readable human freeze approval field, so `freeze-ready` is a readiness check, **not** a GT freeze operation or proof of human approval.
