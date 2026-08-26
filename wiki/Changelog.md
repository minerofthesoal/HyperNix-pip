# Changelog

Full per-release notes for `hypernix`. The top-level `wiki/Home.md`
keeps a running "recent highlights" list; this page is the canonical
history. Semver-ish: minor bumps add features, patch bumps are bug
fixes and UX papercuts. Dates are `YYYY-MM-DD` for PyPI-published
releases; in-branch commits between releases are grouped under the
next release header.

## Legend

- ✨ new feature
- 🐛 minor bug fix
- 🛡️ UX / error-message polish
- 📚 documentation
- 🔧 internal / plumbing
- ✂️ cut / remove
- 🛜 website update / pages update
- 🔁 refactor / integration improvement 
- 𖢥 major bug fix
- ꩜ restore to older version of item
- ❗ unfixed known bug
## 0.72.2.post2 — "0.72.2-2"

𖢥 **`run_tailscale.sh` told you to run a command that does not work.**
With `T1_TOKEN_SECRET` unset it failed with

```
run_tailscale.sh: line 36: T1_TOKEN_SECRET: set T1_TOKEN_SECRET (python3 -c import secrets;print(secrets.token_hex(32)))
```

and that command is a syntax error in both the shell and Python. The
cause is `${VAR:?message}`: the message goes through quote removal before
it is printed, so the single quotes around the `-c` argument were stripped
on the way out. The source looked correct; only the output was wrong. It
is now an explicit check printing a block that has been paste-tested.

𖢥 **Neither example script read the secret `install-t1.sh` had already
written.** The installer generates a stable `T1_TOKEN_SECRET` into
`~/.hypernix/t1api/.env`, and both scripts ignored it — so an operator
who had just run the installer was told to go and make one. Both now
resolve in order: the environment, then that file, then generate (local)
or fail with instructions (tailnet). The file is read one assignment at a
time rather than sourced, since sourcing runs whatever is in it.

🐛 `run_local.sh` minted a throwaway secret on every run even when a
stable one existed, so every restart silently invalidated every scoped
token already issued.

🐛 `run_tailscale.sh` had no `[t1api]` preflight, so a missing extra gave
a clear message on the local path and a bare `ModuleNotFoundError` on the
tailnet one. Both check now.

🔧 `tests/test_t1api_example_scripts.py` covers the deployment scripts:
that no `${VAR:?...}` message contains quotes, that the commands a failure
suggests actually parse, the three-step secret resolution including
quoted values in `.env`, and that a stable secret survives a restart.
Reverting the shipped line fails seven of them.

## 0.72.2 — the installer

✨ **`install-t1.sh`** — an interactive setup and installer for the T1
API. It installs the package, asks what kind of deployment this is, and
writes a configuration that matches: identity and bind address,
deployment kind, key policy, T2 admin password, connection allowlist,
rate limits, cost accounting, model source, HyperLink, and the `waiter`
manager TUI. Then `.env` at 0600, a start script, optionally a systemd
unit and a registry template, an admin key, and a seeded allowlist.

`--dry-run` writes nothing, `--non-interactive` takes every default, and
a re-run backs up an existing `.env` with a timestamp rather than
overwriting it. bash 3.2 throughout, so it runs on a stock macOS without
installing a shell first.

𖢥 **The admin key it minted was invisible to the server it configured.**
The installer minted into `$CONFIG_DIR/keymaster`; `Keymaster()` reads
`~/.hypernix/keymaster` and had no way to be told otherwise. So every
install ended by printing an admin key, under "shown once, copy this
now", that the server had never heard of. `T1_KEYMASTER_DIR` makes the
store configurable — unset it still means the long-standing default —
and the installer now points the server at the store it minted into.
This also makes two T1 servers on one machine stop sharing one key
store.

𖢥 **"T2 only" was a label, not a policy.** The installer offered three
key policies and the server had switches for two: `accept_t2_keys` can
refuse T2 keys, but nothing could refuse the T1 spelling, so choosing
"T2 only" silently behaved as "both" — an operator would believe a
migration was enforced when it was not. `T1_ACCEPT_T1_KEYS` is the
missing half. Both switches off is refused at startup rather than
serving a process nothing can authenticate to.

🛡️ **The T2-only lockout that fix would otherwise have created.** Under
T2-only the minted key is in the T1 spelling — the one the server has
just been told to refuse — and there is no second admin key to undo the
setting with. The installer now hands over the T2 form of that key, and
the refusal message names the family it wants rather than saying the key
is invalid. Admin authority comes from the key store, not the T2
password component, so the wrapped key is a real admin credential.

🛡️ **The allowlist is read back from the database after seeding.**
Reporting a configured whitelist that is not configured is the worst
thing this script could do — the operator is locked out of their own
server with no way in short of editing the database. Seeding failures
now name the problem, and the verified CIDR list shown on success is
tagged and extracted rather than scraped from a capture that also
carries the interpreter's stderr.

🛡️ **CIDRs are validated at the prompt.** A typo used to abort seeding
partway through, leaving the whitelist on and half-populated. The prompt
now re-asks, using the same `ipaddress.ip_network(strict=False)` the
server's `parse_cidr` uses, so a value accepted at the prompt is accepted
by the server.

🐛 A `tr -dc ... < /dev/urandom | head -c N` in the secret generator died
of SIGPIPE under `set -o pipefail`, killing the installer partway
through. Bounded with `head -c` first, trimmed with `cut`.

🐛 `curl | bash` and `answers | ./install-t1.sh` are now distinguished, so
piped answers are not discarded in favour of a terminal that may not
exist.

🛡️ A stale `.pth` in a system Python printed a raw traceback under
"Checking this machine", which reads like the installer crashed. Now one
warning line naming the file.

📚 [Roadmap](Roadmap.md) — **0.72.3: payment connections on a T2 key**, so
a key can be issued to someone who pays for their own usage. Roadmap
only; nothing is implemented.

## 0.72.1 — T1 v1.0.26.8.1.0

The T1 API moves to `1.0.2026.8.1.0` — a feature bump inside the same 1.0
generation, so every existing client keeps working. Three new modules,
the T2 key system, four new endpoints, and a GUI.

### T2 keys

✨ **The T2 key family.** T2 keeps T1's structure and adds the three
things T1 has no room for: an access level (1–9) in the suffix, an
optional 7–13 character admin password in the prefix, and an SSPKID. A
T2 key converts to a valid T1 key and authenticates against the store
that already holds it, so there is no migration — an operator wraps an
existing T1 key at a stated level and both spellings work.

𖢥 **The conversion had a real bug, caught by round-tripping 3000 keys.**
The T2 special-character alphabet excluded `-` on the theory that it is
the suffix separator. It is, but the suffix is anchored at the end and
the special block is five characters at a fixed offset, so a `-` inside
it was never ambiguous — and excluding it meant any T1 key whose
specials contained one converted to a *different* T1 key, which then
failed to authenticate. The alphabets are now identical and
`to_t1(from_t1(k)) == k` exactly, which is the property the whole
compatibility story rests on.

✨ **T2S**, the HyperLink key: exactly 26 body characters, never an admin
(admin is carried by the password component and a T2S key cannot have
one), and outside HyperLink narrowed to read and non-admin write. That
narrowing is what makes a typeable credential acceptable rather than a
liability.

✂️ **T2C is reserved and `generate()` refuses it.** The specified key
derivation — the holder's public IP, shuffled — is not a secret: it is
observable by every server the client contacts, changes without notice,
and is shared across a NAT. It gets a real key-agreement step in the 1.x
line or it does not ship. The type is kept so the wire format has a
place for it.

✨ **SSPKIDs.** A V1 Server ID identifies a server; an SSPKID identifies
one key on it. Many keys per server, one key per SSPKID, enforced by
`ServerKeyRegistry`. The index codec is a greedy decomposition over the
specified symbol table (5=`!`, 10=`?`, 15=`•`, 25=`*`, 40=`^`, 75=`€`,
100=`$`) with a trailing 1–4 digit: it round-trips and is injective over
every index, and non-canonical spellings like `!!` are refused rather
than silently resolving to the same key as `?`.

🐛 **`generate_admin_password` could emit passwords its own validator
rejected.** Uniform choice over 61 characters produces a
three-character run (`abc`, `789`) about 0.6% of the time, so roughly
one caller in two hundred saw a confusing failure. It now uses bounded
rejection sampling.

❗ The **T2 API** itself does not ship until 1.x. What ships here is the
key system and T1's ability to recognise it; `t2_api_available()` is the
single gate.

### T1 API v1.0.26.8.1.0

✨ **`/t1/auth/undo` and `/t1/auth/redo`**, aliased under `/auth/t1/` so a
client that learned `/auth/t1/rotate` does not have to learn a
differently shaped path for the operation that reverses it. The history
stores an *inverse* rather than a snapshot and refuses to record an
operation it could not actually reverse — an undo stack that lies about
what it can restore is worse than none. Payloads carry key material for
rotations, so they are Fernet-encrypted when the `security` extra is
present, bounded by both age and count, and never returned by any
endpoint that lists them.

✨ **`/backup/list` and `/backup/restore`**. A snapshot captures
registries and metadata and deliberately excludes four things: key
material (a backup that restores working credentials is a credential
distribution mechanism), usage counters (restoring them either
resurrects spent quota or refunds it), the audit log (one you can roll
back is not an audit trail), and attachment blobs (hashes only, so a
restore can report what is missing). Restore is a dry run unless
confirmed, and section checksums are verified first — restoring half a
corrupt snapshot is worse than restoring none.

🛡️ `GET /status` now reports `server_name`, `host_id` and `server_id`.
Without a name to match on, `waiter -F "workshop-box"` was silently
unsatisfiable.

### HyperLink

𖢥 **HyperLink refusing to connect** had one cause: pairing was the only
way in. A device whose code expired mid-setup had no fallback, because
a T1 key is 48 characters of mixed symbols. The principal resolver now
accepts a T2 or T2S key alongside the `HLNK_` device token, branching on
the credential's own shape.

✨ **Hugging Face downloads**, PyTorch or GGUF, gated or public, with a
token. Built entirely around resumption: files land at `.part` and are
renamed only when complete, partials resume with a `Range` request, and
a server that ignores the range header is detected by its 200 and the
file restarted rather than appended to — appending would have produced a
corrupt model that downloaded "successfully". Selecting PyTorch files
prefers safetensors and drops the `.bin` duplicates, so a 70B model is
not 260 GB of transfer for 130 GB of weights. Tokens are redacted from
every log line. The download runs on the server, queued as a job.

### waiter

✨ **`waiter -F <target>`** finds a server by name, 54-character Host ID,
`api.jsonl` endpoint, or address — told apart by shape, which works
because the identifier formats are mutually exclusive by construction.
`-l` restricts the sweep to this machine and this LAN; without it the
tailnet is included. That distinction is not cosmetic: a tailnet sweep
touches every peer on a private network. The LAN sweep deliberately does
not walk a /24 either — that is a port scan of a home network.

🛡️ **A host may name a client application in `api.jsonl`; waiter reports
it and does not run it.** `--open` always launches HyperNix's own
`hyped-pro` with HyperNix's own flags. Running a command the remote
machine chose, because it asked, is remote code execution with extra
steps, and a discovery protocol that does it only has to be lied to once.

### New modules

✨ **noodle** (`hypernix.interfaces.noodle`) — agents and swarms across
nine providers (OpenAI, Anthropic, Kimi, Gemini, Qwen, Grok, HyperNix
T1, Ollama, vLLM) in three wire formats. Ten sandboxed tools: create,
edit, read and execute files; web search; memory read and write; context
compaction; todo create and update. Every path resolves *before* the
containment check so a planted symlink cannot escape; execution is
opt-in, argv-only and runs with a minimal environment; memory is off
unless the server enabled it. Self-correction is bounded and evidenced.
The swarm does not fail a task over to another provider on its own —
silent escalation produces a surprising invoice and silent demotion
produces surprising output.

✨ **steamroller** (`hypernix.quant.steamroller`) — the descending
quantiser. Every descent below Q3_K_L stages through it, because a
single pass has to choose every group scale from the full-precision
distribution at once and at one bit there are not enough levels left.
Targets: Q8_0, Q3_K_L, IQ1_M, and the HyperNix extension types IQ0.9_L,
IQ0.75_M and IQ0.5_XXXL. ❗ Those three are **not upstream llama.cpp
quant types** — stock llama.cpp will refuse the resulting GGUF — and
every plan reaching them warns that below ~1.5 bits a model stops being
a worse version of itself.

✨ **scriptgen** (`hnx scriptgen`) — a dense Tk GUI over 43 parameters,
with a headless CLI fallback because the machine with the GPU usually
has no display. Dark slate, charcoal, obsidian and HyperNix red; the
"no purple" rule and WCAG contrast are enforced by `audit_palette()`
rather than by taste, and it caught the first draft of the palette
drifting cool. Generated scripts are readable training loops, not
wrappers.

✨ **livestream** (`hypernix.monitoring.livestream`) — a hand-written
WebSocket server streaming logs, subagent thoughts, GPU/CPU/RAM metrics
and progress to a browser. Each viewer has a bounded queue and one that
falls behind is dropped rather than waited for: a dropped viewer
reconnects, a stalled trainer is an hour of GPU time.

### Quantisation and hardware

✨ **The format registry** (`hypernix.quant.formats`) covers NF4, INT8,
FP8, FP4, the GGUF tiers, EXL2, AWQ and GPTQ, each carrying a minimum
compute capability — so the tuner can filter to what a card can actually
execute. FP8 on Pascal is a missing instruction, not a slow path.

✨ **Pascal auto-tuning** (`hypernix.system.pascal`) for GTX 1080/1080 Ti,
P40, P4 and P100. The load-bearing fact is that FP16 arithmetic is 1:64
on GP104/GP102 and 2:1 only on GP100, so the right answer on a 1080 is
FP16 storage with FP32 compute and on a P100 it is not — the tuner
distinguishes them. `FP16Guard` is the NaN mitigation Pascal needs
because it has no BF16: dynamic loss scaling, skip-on-overflow, and a
hard FP32 fallback once loss scaling is demonstrably not rescuing the
run.

✨ **6-bit momentum** for Pressure Cooker v5, v5+, v5s and v6, in three
packing modes. `aligned` is the right default on Pascal and the wrong
one on a modern card, which is what the tuner decides.

📚 Version and package: T1 API `1.0.26.8.1.0`, package `0.72.1`.

## 0.72.0 — T1 v1.0.26.8.0.1

The T1 API stops tracking the package version. The two ship together but
answer different questions — "which pip release is this" versus "which
API contract is this" — and a client pinning a contract could never
derive one from `0.71.5rc2`. From here the API versions itself.

✨ **The T1 API's own version scheme.** Six parts:
`api.major.year.month.feature.fix`, in two spellings of one value —
`1.0.2026.8.0.1` for changelogs and `1.0.26.8.0.1` for the wire, where
people type it. Both parse, with or without a `v` / `t1 v` prefix, and
they compare equal; a three-digit year raises rather than being guessed
at, because a typo that parses is worse than one that does not.
`generation` (`1.0`) is what a client pins against. `GET /status`
reports both spellings and the parsed components; its `beta` field says
`t1-1.0` and keeps its name, because Beta 3 clients read it and renaming
a field is a breaking change for a cosmetic win. See
[wiki/T1-API.md#versioning](T1-API.md#versioning).

✨ **The LM Studio bridge** (`hypernix.bridge`, `/bridge/lmstudio`,
`waiter lmstudio`). Borrow a model already loaded in LM Studio — on
localhost, across the LAN with CORS on, or over a tailnet. It prefers LM
Studio's native `/api/v0/models` over `/v1/models` for the one fact the
OpenAI shape cannot express: whether a model is actually *loaded*.
`/v1/models` lists everything downloaded, and a chat against an unloaded
model either stalls on a just-in-time load or fails outright, so
"appeared in a list" is not treated as "resident". `waiter lmstudio
status` reports the CORS state explicitly — it only matters for a browser
or WKWebView talking to LM Studio directly, and "works from curl, not
from the app" is otherwise a long afternoon. `waiter lmstudio local`
probes from the machine you are sitting at, with no T1 server involved,
which is what you want when working out why the server cannot see it.
The bridge sits behind the T1 API rather than being called directly so
that authentication, scopes, rate limiting, the audit log and usage
accounting all apply unchanged — and so LM Studio only has to be
reachable from the *server*, not from every client.

✨ **HyperLink pairing** (`/hyperlink/pair`, `waiter hyperlink pair`). A
48-character T1 key is not typeable on a phone, so enrolment is a
two-step exchange: the PC mints a six-character code — from an alphabet
with no `0/O/1/I/L`, valid ten minutes, single use, five attempts — and
the phone redeems it once for a device token stored only as a SHA-256.
Losing a phone revokes that phone. A device is never an admin whatever
key paired it: a stolen phone cannot enrol a second one. It *can* unpair
itself, because that is the app's "sign out" and requiring an admin
would leave a wiped phone's token valid until somebody noticed.

✨ **Server-side chat sessions** (`/hyperlink/sessions`). Append-only,
with the answering model recorded per message — people switch models
mid-thread, and "which model said this" is the first question asked when
re-reading one. Context is trimmed by token budget rather than message
count, because a fixed "last 20" either overflows a small context window
or wastes a large one. A device's owner is the key that paired it, not
the device id, which is what makes a conversation started on the desktop
continue on the phone while another operator's stays invisible.

✨ **The attachment store** (`/hyperlink/files`). Content-addressed by
SHA-256: re-sending the same screenshot costs nothing, ids cannot be
enumerated, nothing is ever overwritten, and deletion is
reference-counted so one message's copy going away does not take
another's bytes. Content type is decided by magic bytes first, then the
filename, then the client's claim — a `.png` that is really a zip is
labelled a zip. At inference, images become vision parts, text and code
become a fenced block with the filename in the fence info, and anything
else becomes a one-line note so the model can decline rather than
hallucinate. Downloads are always `Content-Disposition: attachment` with
`nosniff`: this server can be reached from a WKWebView, and a stored
file rendering as HTML in the app's origin would be stored XSS.

✨ **Hugging Face link merging** (`/hyperlink/models/resolve`,
`waiter fetch`). Paste a model page, a direct download link, or both, and
get one complete download plan. Three pieces of knowledge go into "so it
runs properly": a split GGUF is pulled as the whole set whichever part
was clicked (one third of a model is a file llama.cpp refuses); a
vision projector is included, matched to the weights' quantisation,
because without it the model loads and then cannot see images — a much
more confusing failure than not loading at all; and a page and a file
link naming different repositories raises rather than being silently
resolved, since that is two tabs open and the wrong one copied. Accepts
page/tree/blob/resolve URLs, `hf.co`, `hf-mirror.com`, `hf://`, bare
`owner/repo`, and the Ollama-style `owner/repo:Q4_K_M`. With no network
it still builds a plan from an exact file link, split part names
included — a phone on a bad connection should be able to start a
download it has the URL for.

✨ **Endpoint advertisement** (`/hyperlink/endpoints`). Every address this
machine answers on, ranked Tailscale-first, so a client tries them in
order and keeps the one that answers. Nothing to switch when the phone
leaves the house. Authenticated despite looking innocuous: a list of a
machine's internal addresses is reconnaissance.

✨ **HyperLink for iOS** (`ios/`). A SwiftUI app: streaming chat, photos,
file and code upload, per-conversation model switching, and the Hugging
Face resolver, against a home PC on the LAN or over Tailscale. iOS 18
and newer, developed against the iOS 27 SDK. Built and packaged as an
IPA by `.github/workflows/ios.yml` and attached to every GitHub Release
alongside the wheel — unsigned unless the repository has Apple signing
secrets, which is what makes the workflow runnable by anyone. The
`.xcodeproj` is generated from `ios/project.yml` by XcodeGen rather than
committed. See [ios/README.md](../ios/README.md).

𖢥 **A burnt pairing code came back to life.** The attempt cap deleted the
code and then raised inside the same `with backend.connect()` block — and
the connection's `__exit__` rolls back on an exception, so the DELETE was
undone. A code that had exhausted its five attempts was refused once and
then worked again on the next try: the exact opposite of a cap.
Validation, enrolment and cancellation now happen in one transaction and
the failure is raised after it closes. One transaction, not two, because
two phones redeeming the same code at the same moment must not both pass
a check-then-insert.

🐛 **A mistyped pairing code reported the wrong problem.** Normalisation
stripped every character outside the pairing alphabet, so one wrong
keystroke silently shortened the code to five characters and the user was
told "a pairing code is six characters" — an error about something they
had not done. Only separators are stripped now; a stray character
survives, the length check passes, and the lookup fails with "unknown
pairing code", which is true and actionable.

🐛 **`LMStudioModel.publisher` ignored the field it was given.** An
operator-precedence slip — `str(a or b if c else "")` parses as
`str((a or b) if c else "")` — meant a model whose id had no `/` in it
reported no publisher even when the API supplied one.

🐛 **`ResolvedModel.file_count` existed only in `to_dict()`.** Every
Python caller had to serialise the object to ask it how many files were
in the plan.

🔧 `hypernix.t1sdk` and `waiter` gained typed methods for all of the
above; `waiter` gained `lmstudio`, `hyperlink` and `fetch` subcommands.
`T1_ENVIRONMENT=production` now refuses to start with `T1_LMSTUDIO_URL`
pointing at a non-loopback, non-Tailscale `http://` address, since that
sends prompts across the network in the clear. Tailscale is exempt —
WireGuard already encrypted it.

📚 [wiki/T1-API.md](T1-API.md) gains Versioning, The LM Studio bridge,
HyperLink and Hugging Face link merging sections, plus the new endpoints
and environment variables. [ios/README.md](../ios/README.md) covers
building, sideloading, and how the app is put together.

## 0.71.5rc2

𖢥 **`hyped-pro`'s Escape key cancelled nothing.** It set a flag that made the TUI *discard* the answer when it eventually arrived — the model kept generating, a cloud call kept billing, and the prompt stayed locked the whole time. The cause was one layer down: the bridge dispatched every request inline off its stdin loop, so a ninety-second `chat` held that loop for ninety seconds and a cancel sent at second two wasn't *read* until second ninety-one. Long commands now run on their own thread while the loop stays free to read `cancel`, each in-flight request owns a `threading.Event`, and the local generation loop polls it once per token. The reply says which actually happened rather than implying more than is true: `stopped` for a local safetensors model, `pending` for a cloud call or llama.cpp inside multilama — neither has an interruption point, so those finish and their reply is dropped. A cancelled turn keeps whatever tokens were produced; only a cancel that produced nothing pops the dangling user turn, which the old code never did at all.

🛡️ **Bridge failures no longer hang the TUI.** Every call now has a timeout sized to what it is (30 minutes for a chat, 10 seconds for a config read) — there was none before, so a wedged bridge froze hyped-pro with ctrl+c as the only way out. A failed spawn settles its pending promises, because Node does not guarantee an `exit` event after one and a missing Python otherwise hung every call forever. The read buffer is cleared when the process dies, so a partial line can't corrupt the first response of its replacement.

𖢥 **`neo_oven.stream()` mangled every non-ASCII character.** It decoded each token on its own, and a token is not a character: "café" streamed as `caf` + two replacement characters, and any emoji or arrow came out as one `�` per byte. It now decodes the whole sequence each step and emits only the new suffix, holding back a character whose bytes haven't all arrived. It also honours stop sequences (holding back any tail that could still *become* a marker, so `
class ` can't leak out one character at a time) and takes a `seed` — without those, the streamed answer and the non-streamed one for the same prompt were simply different text. Joining `stream()` now reproduces `complete()` exactly.

𖢥 **`neo_oven.fill()` could never stop early.** It passed no `eos_ids` at all, so every call ran the full `max_new_tokens` and returned whatever the model rambled into after finishing the middle. It now stops at EOS and at the FIM markers, and trims at FIM-appropriate stops — `
def ` is a perfectly ordinary thing to generate when filling a hole in existing code, so the completion stop list was the wrong one to apply.

🐛 **EOS was being appended before the loop broke on it**, so the terminator was part of the returned sequence. This only ever looked correct because HF decode is asked to skip special tokens; a byte tokenizer, or an EOS the tokenizer doesn't class as special, would have emitted it verbatim.

🐛 **`max_position_embeddings` was read unguarded** on every generated token, turning a model whose config lacks the field into an `AttributeError` at the first token rather than a clean failure at load.

✨ **A cooperative `should_stop` hook** on `NeoOven.complete`/`chat`/`fill`/`stream`/`generate_batch`, polled once per token. It's what makes the TUI's Escape real for local models, and it returns whatever was generated before the stop rather than discarding it.

✨ **T1 API — Beta 4, and the release candidate.** `POST /usage/report`, `hyped-pro` against a real T1 API server, automatic `PATH` setup, and the `qwen3.8-27b` registry entry. `GET /status` now reports `beta: "beta4"`.

✨ **`POST /usage/report` — the endpoint that makes remote quota real.** Beta 3 could route a request and refuse an exhausted model, but nothing could report consumption back: `UsageMeter.record` had no HTTP surface at all. For any client that runs inference itself, that meant the per-model counters never moved, so the quota cascade never advanced past its first model and per-model limits were unenforceable in practice. Three rules keep it safe to expose to every authenticated key: usage is recorded against **the caller's own key**, never a body-supplied one; the model must be registered *and* allowed for that key; and counts are non-negative and capped, so a report can add usage but never subtract it — a client that could report negative tokens could refund itself quota, which would make every limit in the system advisory. A report that exhausts a model still succeeds (the tokens really were spent); the refusal belongs on the *next* route call, not on the accounting for work already done.

✨ **`hyped-pro` talks to a real T1 API server, local or remote.** New `t1api` vendor and a `t1-routed` model. The division of labour follows the T1 API's own design principle — the client is never trusted to decide what it may access: the **server** authenticates the key, decides which model it may use (`POST /models/route` walks the quota cascade) and owns the counters; the **client** runs that model and reports the tokens it spent. Passing a `model_id` is a *request*, not a choice — the server confirms or refuses it, and the client runs whatever the server said. The server has no inference endpoint, so it never sees prompt text, only token counts; that's a privacy property worth keeping rather than an omission to work around. New `/t1api` command in the TUI, new `t1api_status` / `t1api_get_url` / `t1api_set_url` bridge commands, and `HNX_T1_API_KEY` / `HNX_T1_API_URL` alongside a persisted `t1_api_url`.

✨ **`t1-routed` names no weights, on purpose.** Its `repo` is empty because the real model is whatever the server routes to. Server `model_id`s are stable slugs and this catalog uses short names; the two agree only by coincidence, so the mapping is an explicit `t1_api_model_map` setting with an exact-name fallback and **no fuzzy matching** — running a *similar* model to the one the server authorized would be worse than refusing. When nothing maps, the error names the model, the config key, and the command to fix it instead of quietly running something else.

✨ **`hypernix path` — console scripts that are actually on `PATH`.** `pip install --user` puts ~20 scripts in a directory many systems don't have on `PATH` (Debian's `~/.profile` only adds `~/.local/bin` if it already existed at login), so `pip install hypernix` followed by `hypernix: command not found` looked like a broken package rather than a `PATH` gap. `hypernix.system.pathfix` writes one idempotent, clearly-marked, reversible block into the startup file the person's shell *actually reads* — `~/.bashrc` on Linux, `~/.bash_profile` on macOS, `$ZDOTDIR/.zshrc`, a `conf.d` file for fish, a PowerShell profile on Windows. `--undo` takes it back out; `--check`, `--print` and `--force` cover the rest. Wired into `hypernix doctor` (reported) and `doctor --fix` (repaired).

🛡️ **The `PATH` fix runs automatically, and refuses more often than it acts.** It does nothing when the directory is already on `PATH`, when `HYPERNIX_NO_PATH_SETUP` is set, in CI, or after it has already tried once — so someone who deleted the block doesn't get it silently written back. Above all it refuses **inside a virtualenv or conda env**: that directory belongs to one environment and is on `PATH` only while activated, so baking it into `~/.bashrc` would leak that environment into every shell the person ever opens. It always prints what it changed and how to undo it — a `PATH` edit that happens invisibly is worse than no `PATH` edit. It hangs off the console-script and `python -m hypernix` entry points rather than `cli.main`, so calling the CLI in-process never touches a home directory.

✨ **`hyped-pro` shows the current public release.** `hypernix.system.release` reads PyPI's JSON API once per six hours per machine, caches to `~/.hypernix/release-cache.json`, times out fast, and returns "unknown" instead of raising — a banner is not worth a hung TUI on a machine with no network. `HYPERNIX_NO_VERSION_CHECK` (already honoured by the launcher) turns it off. Pre-releases are tracked separately from stable ones: telling someone on `0.71.5rc2` to "upgrade" to an older stable release would be wrong, so that reads as a pre-release note, not an update prompt. New `/version` command; the status box and banner carry the label.

✨ **`qwen3.8-27b`** — in the download registry (`Qwen/Qwen3.8-27B`) and in the hyped-pro catalog. The catalog entry points at the GGUF build with a conservative partial-offload default, because that's the one that actually fits a consumer card; the safetensors repo is what `hypernix download` resolves.

🐛 **`hypernix.__version__` was `0.71.5postr1`**, which is not a valid PEP 440 version — pip normalizes it to something quite different from the intended `post1`, and it disagreed with `pyproject.toml` besides. Every version string in the tree now says `0.71.5rc2`.

🔧 A stray Markdown code fence (` ``` `) was sitting in `.gitignore` as a literal pattern.

## 0.71.5.post1

Everything between Beta 3 and the release candidate: three modules that didn't work, and the documentation site.

𖢥 **`hnx map` didn't find models, and its `acc` setting did nothing.** It now auto-discovers a checkpoint from the working directory (`.`, `checkpoints/`, `out/`, `output/`, `model/`, `models/`), reads shapes from safetensors headers without `torch.load`, and resolves `acc=auto` from the real parameter and layer counts instead of a constant. Errors are drawn in their own banner below the pipeline rather than over the DATA engine, and the module gained the `__main__` guard it needed to be runnable as `python -m`.

𖢥 **`ethanol` (`eth`) claimed to work with no backend at all.** `backend=none` now exits non-zero and says so instead of reporting success. `auto` reads real temperatures and picks a level from them, with a hard abort above 85 °C. Level 0 performs a genuine reset on every backend — ROCm was issuing the wrong subcommands entirely, and Intel was missing its reset flag — so "turn it back to stock" now does that. New `status` and `reset` commands, and the `backend=none` check moved ahead of the confirmation gate so it can't be confirmed past.

𖢥 **`ups` had no entry point, a lock held across a network call, and unbounded history.** The HTTP check and the snapshot callback both moved outside the lock (a slow or hanging endpoint was blocking every other reader), history is capped, and the guard grew `stop()` plus context-manager support so `threat_now()` can't leak a background thread. It now has a real CLI and a `ups` console script — it was a complete module that nothing could run.

🛜 **The documentation site was rebuilt** — structure, type and density only; every colour value is unchanged. Self-hosted Inter + JetBrains Mono (no font CDN), a two-column hero with a terminal transcript, a shared kicker/title/lede rhythm for every section and page, and the 40-card "All subsystems" wall replaced by a grouped, searchable table with stage filters. Fixed along the way: the docs cards ran "wiki ↗" into the page name, and the stats page orphaned "Issues" onto its own row.

🐛 **Two T1 API bugs found by running the server for real**, not by testing it: `waiter doctor` passed a raw dict where a `ServerStatus` was expected, and a key created while the server was running was rejected until restart because the key cache was never refreshed.

🔧 CI fixes for macOS (a long temp path wrapped in `rich` output) and Windows (`WinError 10106` importing `_overlapped` through the anyio plugin), plus a timing race in a synthetic timer test.

## 0.71.5b3

✨ **T1 API — Beta 3: production hardening.** The T1 API is now feature-complete against its spec. PostgreSQL, a durable audit log, mTLS, advanced rate limiting, IP allow/blocklists, real remote multi-server module transport, the key directory, usage cost/estimates/forecasts, the complete SDK, the full `waiter` TUI, and production configuration validation. Full contract in `wiki/T1-API.md`; deployment examples in `examples/t1api/`.

✨ **PostgreSQL for production** — `T1_DATABASE_URL` moves *every* store (usage, servers, modules, jobs, billing, audit, network policy, key assignments) and changes nothing else. The portability lives in one place, `t1api/db.py`: a connection wrapper normalizes placeholders, row-by-name access, DDL dialect and transaction/close semantics, so no store needed an `if postgres:` branch. New `hypernix[t1api-pg]` extra. Existing SQLite databases migrate in place at startup rather than needing a dump and reload.

✨ **The plan is now the server's to decide** — the one deliberately breaking change. Beta 2's `POST /models/route` took `plan` from the request body, which let a client name the most generous plan it could think of. A plan is now a property of an administrator-recorded assignment (`POST /keys/assign`), and a `plan` in the body is an *assertion*: matching is accepted, mismatching returns `AUTH_INSUFFICIENT_SCOPE`. A key can also be narrowed to a subset of registered models, checked on manual selection and on whatever automatic routing lands on.

✨ **Audit logging** — `hypernix.t1api.audit.AuditLog`: durable, queryable, admin-only at `GET /audit`, and reading it is itself audited. Secret-shaped fields are dropped **by name at write time** (`key`, `token`, `secret`, `password`, `authorization`, `dsn`, `credential`), so a future call site that accidentally hands over a raw key cannot write it to disk; identifiers that only look secret by name (`key_id`, `payment_token_id`) are carved out. An audit write never takes down the request it describes.

✨ **Advanced rate limiting** — token bucket *and* sliding window, because they answer different questions: burst-tolerant per-key/per-IP budgets for interactive clients, hard ceilings for operator-forced limits. Runs in **middleware, before the route handler**, which is what "apply rate limits before expensive model operations" has to mean to be true. Expensive endpoints declare a higher cost. Per-process limits are documented as such rather than papered over.

✨ **IP allowlists, blocklists, and the unlisted-client decision** — `hypernix.t1api.netpolicy`, CIDR-matched, persistent. The blocklist wins over the allowlist by design (un-blocking is an *appeal*, which is its own operation), and `T1_ALLOW_UNLISTED_CLIENTS` is the design principle's own "does this server accept non-allowlisted clients at all" as a first-class setting. Blocking your own address is refused — it has no undo through the API.

✨ **mTLS** — direct termination (uvicorn holds the certificates) or proxy termination (nginx forwards `X-Client-*`). The proxy path trusts those headers **only** from an address in `T1_TRUSTED_PROXIES`, because otherwise any client able to reach the process directly could just send `X-Client-Verify: SUCCESS`; proxy mTLS with an empty trusted-proxy list fails closed. Optional subject/fingerprint allowlists, with fingerprints normalized so an allowlist can't silently never match. `/health` stays exempt for load balancers.

✨ **Remote multi-server deployment — real bytes this time.** Beta 2's module sync was bookkeeping and said so. Beta 3 transfers: HMAC-signed over method|path|timestamp|body-digest with a freshness window, SHA-256 verified on both ends, size-capped, and pushed only to a server an admin promoted to trusted — the address comes from the registry, never from the request. Remote fetch refuses redirects, because following one is exactly how an SSRF check gets bypassed. Nothing is ever executed, imported, or interpreted on either side. New `POST /modules/{id}/deploy`, `POST /modules/{id}/fetch`, `POST /modules/receive`.

✨ **The endpoints the spec listed and Beta 1/2 hadn't implemented** — `GET /keys`, `POST /keys/import`, `POST /keys/assign`, `GET /usage/history`, `GET /usage/cost`, `POST /usage/estimate`, plus `GET /usage/by` for the per-model/key/server/module/user/account reports. Cost comes only from recorded usage and the registry's own pricing — there is no second price list, and a model that isn't registered has no price and cannot be costed. Estimates record and reserve nothing; forecasts state the window they extrapolated from and how much to trust it.

✨ **`hypernix.t1sdk` — the complete SDK.** Typed models over every endpoint, an exception hierarchy mapped from the server's stable codes, retries honouring `Retry-After`, mTLS and private CAs, pagination and job-polling helpers, and a `call()` escape hatch so a newer server never blocks on an SDK release. Stdlib only. Non-idempotent POSTs are never retried: replaying `POST /billing/redeem` after a timeout could look like a double redemption. `waiter.client` is now a thin compatibility layer over it rather than a second implementation.

✨ **The full `waiter` TUI** — `waiter tui` / `waiter serv -G`. Eight curses panes covering models, quota, usage and cost, jobs with live progress, servers, modules, an event tail, and settings. Everything comes from the API: a greyed-out model is greyed out because `/models/{id}/availability` said so, and the fallback chain is the cascade the server actually walked, not one reconstructed from registry fields. Refresh runs on a background thread so an unreachable server shows stale data with a banner rather than a frozen terminal.

✨ **Every `waiter serv` flag is now wired.** `-B`/`-W`/`-a`/`-r` call the new security endpoints (and still save locally, which is what survives a non-admin refusal); `-G` opens the TUI; `-Rf` refreshes everything; `-y` mirrors the server's settings into the local config. New subcommands: `keys`, `audit`, `security`, `cost`, `deploy`, `tui`, `doctor`, `smoke`.

✨ **Production configuration validation** — `T1_ENVIRONMENT=production` makes `create_app()` refuse to start on a missing token secret, SQLite, wildcard CORS, no TLS, disabled protections, or the placeholder registry, listing *every* problem at once rather than one per restart. A bad production config should fail the deploy, not surface later as a puzzling 500. The same list is readable without the raising at `GET /status` and via `waiter doctor`.

🛡️ **`waiter smoke`** — the CLI smoke tester (spec deliverable #11). Read-only by default; `--write` adds a self-cleaning module lifecycle check. Expected refusals count as passes, so "non-admin correctly refused `/audit`" passes and "non-admin served `/audit`" fails — the direction a security-relevant tool should be sensitive in.

📚 **Deployment documentation and examples** — `examples/t1api/` ships a two-stage non-root Dockerfile, a compose stack (API + PostgreSQL + nginx, with the API never published to the host), an nginx config that terminates TLS and forwards mTLS headers, a sandboxed systemd unit, local and Tailscale run scripts, and a fully commented `.env.example`. `wiki/T1-API-Security-Checklist.md` is the security audit checklist, ordered by blast radius, with the items `waiter doctor`/`waiter smoke` automate marked as such.

📚 **Generated API examples** — `examples/t1api/API-EXAMPLES.md` and `openapi.json` are produced by `scripts/t1api_examples.py` driving a real server. A hand-written example is a claim about the API; a generated one is a recording of it, and regenerating shows a behaviour change as a diff. Credential-shaped fields are replaced with placeholders before anything is written.

𖢥 **Middleware exceptions were being swallowed.** Starlette only routes exceptions raised inside the application to `@app.exception_handler`; one raised in an outer `@app.middleware("http")` propagates past it. Every Beta 3 security check runs as middleware and signals refusal by raising, so network-policy, mTLS and rate-limit refusals returned a bare 500 with no error code instead of the documented envelope. Found by the new tests.

🐛 **A non-refilling rate-limit rule produced `retry_after=inf`**, which raised `OverflowError` building the `Retry-After` header and would have serialized as a bare `Infinity` — not valid JSON — in the response body. The limiter now reports `None` ("not by waiting") and the header is omitted rather than guessed at.

🐛 **`%` inside SQL string literals wasn't escaped for psycopg**, so a query containing a `LIKE '%…%'` pattern would have been a syntax error on PostgreSQL and nowhere else.

🐛 **`ModelEntry` coerced its enum fields in `from_dict` but not in `__init__`**, so a directly-constructed entry kept plain strings and failed with `AttributeError` at serialization time, far from the construction that caused it. Normalized in `__post_init__`.

🐛 **A disabled `AuditLog` skipped creating its table**, so reading it raised "no such table" instead of returning nothing. `enabled` now gates writes only.

🐛 **Fixed three pre-existing CI failures on macOS and Windows.** `test_assistant.py` asserted a full tmpdir path appeared verbatim in console output, which fails when rich wraps the longer macOS tmpdir path at 80 columns. `test_autofix_scripts.py`'s synthetic "always fails" timer test was itself a race — measured, it lost that race 1997 times in 2000 — so on a fast runner it passed, `autofix-F` correctly stood down, and the tests expecting it to act failed; it now busy-waits a fixed margin and fails 8/8 before the repair and passes 8/8 after. And `autofix-F`'s inner pytest run crashed on Windows before executing a test, because pytest autoloaded anyio's plugin, which imports asyncio, which imports `_overlapped`, which fails on the GitHub Windows runners with `WinError 10106`; that run takes no third-party plugins and now says so.

🔧 **Model limits in `GET /models`** — `context_limit`, `input_token_limit`, `output_token_limit` and `tool_call_limit` are now in the list response, not just the detail one. Displaying model limits is a TUI requirement and a client rendering a list shouldn't need one request per model to fill three columns. Additive.

🔧 **Destructive operations require `?confirm=true`** (`DELETE /servers/{id}`, `DELETE /modules/{id}`), controlled by `T1_REQUIRE_DESTRUCTIVE_CONFIRMATION`.

🔧 **Security response headers** on every response, error responses included: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`, and HSTS when TLS is on.

🔧 **Tests** — `tests/test_t1api_beta3_security.py`, `test_t1api_beta3_core.py`, `test_t1api_beta3_http.py`: network policy, rate limiting, mTLS, audit scrubbing, PostgreSQL translation (with a real round-trip when `T1_TEST_DATABASE_URL` is set), keys and plan resolution, cost and forecasts, transport signatures, deployment, production validation, and the middleware order. The Beta 1/2 HTTP suites had never actually been executed — their authoring sandbox had no network to install FastAPI — and now run; two assertions that had been asserting the wrong thing are corrected, including one that expected the placeholder registry entries to be routable when the whole point is that they are not.

𖢥 **A key created while the server was running was invisible until restart.** Keymaster reads its key files once, at construction, so the documented quickstart — `gkey create`, then point `waiter` at the already-running server — returned `AUTH_INVALID_KEY` for a brand-new key. `T1AuthService.validate_key` now refreshes the key store once on an unknown key, throttled to at most one reload every five seconds because it is disk I/O an unauthenticated caller can reach. Found by running the quickstart against a real uvicorn process instead of a `TestClient`.

🐛 **`waiter doctor` crashed against a real server** with `'dict' object has no attribute 'environment'`: waiter's client overrides `status()` to return the raw envelope for the CLI's table renderers, and doctor assumed it got the typed object. Same cause as above — nothing in a TestClient-driven suite exercised that path.

❗ **Known limitation** — module blobs are checksummed and path-sanitized but **not encrypted at rest**; the store relies on filesystem permissions. Everything else that needs at-rest protection has it (T1 keys via Keymaster, payment tokens as hashes, waiter config via `-E`). This is the one Beta 3 line item deliberately left open rather than half-done.

## 0.71.5b2

✨ **T1 API — Beta 2** — Module registry, server registry, async jobs, event streaming, the model routing/quota-cascade engine, and billing/payment-token support. Matches the spec's Beta 2 scope; full contract in `wiki/T1-API.md`.

✨ **Model routing & quota cascade** — `hypernix.t1api.routing.RoutingEngine` walks a plan-scoped, data-driven cascade (`t1api/data/routing_policies.example.json` ships the spec's own free-tier and paired-plan examples verbatim, including the paired-plan detail that N^3 falls back to `nanonix-mini` — *not* `nanonix-mini-lite`). Manual model selection never silently substitutes: an exhausted model raises `MODEL_QUOTA_EXHAUSTED` unless `automatic_fallback=True`. New `POST /models/route` (an addition beyond the spec's literal endpoint list — the spec describes routing behavior but doesn't enumerate an endpoint for it).

✨ **Server registry** — `hypernix.t1api.servers.ServerRegistry`, SQLite-backed. Servers register `untrusted` by default; only an admin can promote to `trusted` (or register directly as `local` for the operator's own address). `require_trusted()` is what module sync checks before treating a server as a valid target.

✨ **Module system** — `hypernix.t1api.modules.ModuleRegistry`: create, local upload (checksummed, path-sanitized), remote-source *registration* (SSRF-validated, never auto-fetched), versioning, and sync-tracking. Never executes, imports, or interprets anything it stores — a module is an opaque blob or a validated-but-unfetched URL, by design.

✨ **Async jobs** — `hypernix.t1api.jobs.JobQueue`: `queued → running → succeeded|failed|cancelled`, a real `ThreadPoolExecutor` (not just synchronous stubs), pluggable per-kind handlers (unregistered kind → `NOT_SUPPORTED`), cooperative cancellation tested against a genuinely in-flight background job. One real handler ships: `module_sync`, composed in `t1api/app.py` from `ModuleRegistry` + `ServerRegistry`.

✨ **Event streaming** — `hypernix.t1api.events.EventBus`, in-process pub/sub. `GET /events` polls (`since_id`/`type`/`limit`); `GET /events/stream` (addition beyond the spec's list) is an SSE live tail. Jobs auto-publish `job.<status>` events for any kind with zero per-handler code; servers/modules publish from their routers.

✨ **Billing ledger** — `hypernix.t1api.billing.BillingLedger`. **Internal ledger, not a payment-processor integration** — no Stripe/card-network call anywhere. Admin-minted payment tokens (`POST /billing/payment-token`) return their raw value exactly once and store only a SHA-256 hash; redemption (`POST /billing/redeem`) is single-use (`PAYMENT_TOKEN_ALREADY_REDEEMED` on a second attempt); every transaction is masked in API responses (`txn_abcd1234…`).

🔒 **New security guardrails** — `hypernix.t1api.security`: SSRF guard (`validate_remote_address`, blocks non-http(s) schemes and the cloud-metadata IP unconditionally; private/loopback addresses need explicit `allow_private=True`, the knob Tailscale/local deployments use) and path-traversal guard (`sanitize_module_path`) for local uploads. Both are shared by the server registry and module system rather than duplicated.

🔧 **Local/Tailscale deployment documented** — new subsection in `wiki/T1-API.md#installation`: bind to `0.0.0.0`/the Tailscale interface, pass `allow_private_address=True` on server registration.

🔧 **Tests** — `tests/test_t1api_routing.py`, `test_t1api_security.py`, `test_t1api_servers.py`, `test_t1api_modules.py`, `test_t1api_jobs.py` (including real threaded execution + cancellation), `test_t1api_events.py`, `test_t1api_billing.py` — all pure-core, executed against the real implementations, no FastAPI needed. `tests/test_t1api_http_beta2.py` (FastAPI `TestClient`, needs `hypernix[t1api-test]`) covers the new HTTP layer including the full `module_sync` job lifecycle over HTTP.

## 0.71.5b1

✨ **T1 API (`hypernix.t1api`) — Beta 1** — Controlled HTTP gateway into HyperNix-pip, built as a mountable FastAPI module (`hypernix.t1api.create_app`). Implements the spec's Beta 1 scope exactly: core FastAPI server, T1 authentication + scoped tokens, model registry, basic per-key/per-model usage tracking, `/health` `/status` `/models` + auth/usage/config endpoints, SQLite storage, OpenAPI docs. Full contract in `wiki/T1-API.md`.

✨ **Model Registry** — `hypernix.t1api.registry.ModelRegistry` is the single source of truth for which models the T1 API exposes; unregistered `model_id`s always return `MODEL_NOT_SUPPORTED`, never silently fall through to a client-supplied path. The nine example models from the spec (HyperNix 1, Ryiver 1, nanoNix, ...) ship as seed data but are invisible by default (`status: "example"`) — set `T1_ENABLE_EXAMPLE_MODELS=1` to make them selectable for local testing.

✨ **Auth integration, not reimplementation** — `hypernix.t1api.auth.T1AuthService` wraps the existing `Keymaster`/`Gatekeeper` rather than duplicating key storage or quota logic, and adds short-lived HMAC-signed scoped tokens (`POST /auth/token`) on top. Admin-only `POST /auth/t1/admin/rotate` implements "convert a normal T1 token into an admin token only when the authenticated user has the required permission."

✨ **Usage metering** — `hypernix.t1api.usage.UsageMeter` tracks per-key/per-model usage on SQLite (`hypernix.t1api.storage.UsageStore`) and enforces the spec's "either input or output cap hit = fully exhausted, independent per model" rule via `MODEL_QUOTA_EXHAUSTED`.

✨ **`waiter` — the official T1 API TUI/CLI** — New `waiter` console script (`hypernix.waiter`), zero hard deps beyond core `hypernix` (stdlib `urllib` client). Implements the spec's single-command automatic setup (`waiter serv -A -I <server> -K <T1_TOKEN> -E`) plus `models`/`model`/`status`/`health`/`whoami`/`usage`/`config` subcommands. Every `serv` flag from the spec is parsed and accepted; flags needing Beta 2/3 server endpoints (`-B`/`-W`/`-r`/`-a`, full `-Rf`/`-y`, `-G`) store intent locally and print a stable "not wired yet" notice instead of no-op'ing silently. Full flag-by-flag status in `wiki/Waiter-TUI.md`.

🔧 **New optional extras** — `hypernix[t1api]` (`fastapi`, `uvicorn`, `pydantic`, `python-dotenv`) for the HTTP layer; `hypernix[t1api-test]` adds `httpx` for `tests/test_t1api_http.py`. `hypernix.t1api`'s core (registry/storage/usage/auth/config/errors) stays importable without either — same zero-extra-deps-for-core-logic pattern as `hypernix.keymaster`/`hypernix.gatekeeper`.

🔧 **Tests** — `tests/test_t1api_core.py` and `tests/test_t1api_auth.py` (pure-Python core, run against the real `Keymaster`/`Gatekeeper`, no extra deps needed) plus `tests/test_t1api_http.py` (FastAPI `TestClient`, needs `hypernix[t1api-test]`).

📚 **`wiki/T1-API.md`, `wiki/Waiter-TUI.md`** — New pages: architecture, model registry semantics, auth, quota rules, endpoint reference, full Beta 1→4 roadmap table matching the spec's own beta breakdown, security notes.

## 0.71.5a2

✨ **`neo_oven` — Unified Model Management Module** — New `hypernix.neo_oven` module replaces `old_oven`, `old_fridge`, `mediocre_fridge`, and `new_fridge` as the single, production-ready entry point for model loading, generation, training, and evaluation.

✨ **`NeoOven` class** — Full successor to `CodeOven` with identical API (`complete`, `fill`, `chat`, `train`, `save_pt`) plus new capabilities: `stream()` for token-by-token generation, `generate_batch()` for batched inference, inline `freeze_backbone()` / `memory_stats()` / `vram()`, and `build_judge_corpus()` shortcut.

✨ **`JudgeCorpus`** — Replaces `mediocre_fridge` toy script. Proper class-based judge/reward-model dataset builder supporting: `from_pairs()`, `from_oven()` (collect real LLM responses), `from_hf_dataset()` (HF `datasets` integration), JSONL and legacy text serialization, round-trip `load()`, and configurable hard-negative augmentation with 7 strategies (not just 5 character-shuffles).

✨ **`TrainingMetrics`** — Replaces `new_fridge` regex log parsing + static matplotlib. Callback-based metrics collector with native TensorBoard (`SummaryWriter`), Weights & Biases, and MLflow integration. Buffers all steps locally; produces loss-curve PNGs, score histograms, and multi-round plots on demand via `plot_loss()` / `plot_score_distribution()` / `plot_round_losses()`. Export to JSONL via `to_jsonl()`. `NeoOven.train()` accepts `metrics=True` to auto-attach.

✨ **Inline memory management** — `freeze()`, `unfreeze()`, `parameter_stats()`, `offload_to_cpu()`, `chill_cache()`, `vram_stats()` — all previously in `old_fridge`, now unified in `neo_oven` with improved DDP/FSDP/`torch.compile` unwrapping and 7 strategies for hard-negative augmentation.

✨ **`preheat()` / `new_oven()`** — Top-level functional shortcuts identical in call signature to their `old_oven` counterparts, now returning a `NeoOven` instead of a `CodeOven`.

✨ **`parse_training_log()`** — Extended to return structured dicts with `step`, `loss`, `lr`, and `ppl` fields instead of flat `(step, loss)` tuples, while remaining backward-compatible.

🔧 **Backward-compatibility shims** — `plot_loss_curve()`, `plot_score_distribution()`, `plot_round_losses()`, and `synthesize_judge_corpus()` are re-exported from `neo_oven` so callers using the `new_fridge` / `mediocre_fridge` API surface continue to work without changes.

🔧 **Codebase-wide transition** — All internal imports in `cli.py`, `hyped.py`, `hyped_pro_core.py`, `bell.py`, `countertop.py`, and `vera.py` now route through `neo_oven.preheat` instead of `old_oven.preheat`. `old_oven.py`'s internal `old_fridge` dependency was cut and replaced with `neo_oven.unwrap_model`.

✂️ **Legacy modules deprecated** — `old_oven`, `old_fridge`, `mediocre_fridge`, `new_fridge` now print a **bold red** deprecation warning on import (via `rich.Console`) pointing users to `neo_oven`. The files are kept intact for backward compatibility.

🔧 **Tests** — New `tests/test_neo_oven.py` with comprehensive coverage: memory management, `JudgeCorpus` round-trips, `TrainingMetrics` recording and JSONL output, `parse_training_log`, arch preset completeness, and importability checks.

## 0.71.5A1
✨ **Vera Redesign** — Transformed Vera from an AI assistant into a robust smoke-testing and linting tool (`hnx vera`). Added support for `ast`/`ruff` linting, argument testing (`-FT`), dry-runs (`-dr`), full-runs (`-C`), timeout tracking, and `pytest` fallbacks.
✨ **Vera AI Analysis** — When a test fails in Vera, it now surfaces an advanced AI explanation powered by Qwen3.5-4b (`hypernix.neo_oven.preheat`) to identify line numbers and fixes without crashing.
✨ **Pressure Cooker V5S Exposure** — `pressure_cooker_v5s` is now directly importable from the top-level `hypernix` namespace (and aliased as `pressurecooker_v5s`).

## Unreleased
✨ **`PressureCookerV6` / `PressureCookerV6V`** — new speed-first optimizer
generation, deliberately the opposite tradeoff from V5/V5S's
memory-first design. `PressureCookerV6` ("Single-State Trust Momentum")
drops V5's whole feature set — no oscillation tracking, no curvature
estimate, no quantized momentum, no per-parameter Python-level `float()`
syncs — down to a single fused momentum buffer updated via
`torch._foreach_*` multi-tensor ops, with at most one batched
host↔device sync per step (for an optional LARS/LAMB-style trust ratio)
instead of several per parameter tensor. Real, measured numbers, not
estimates — from `scripts/benchmark_v6.py` and the now-V6-aware
`scripts/measure_optimizer_memory.py`, both included in this change:
**0.5x AdamW's optimizer-state bytes** (one fp32 buffer instead of two,
exact across every hidden size measured) and **1.59x AdamW's step time
on CPU** (this environment has no CUDA device — the design specifically
targets host↔device sync and kernel-launch overhead, which matters far
more on GPU than CPU, so that ratio is reported as a CPU number, not
extrapolated). `PressureCookerV6V` adds CUDA graph capture
(`warmup_graph`/`replay_graph`, identical contract to
`pressure_cooker.ProCooker`) and optional `torch.compile` on top,
requiring at least one CUDA parameter; falls back to eager execution
with a warning if `torch.compile` is unavailable or fails, never raises
for that. No Pascal-specific `Agedcookerv6` tier — V6 never touches
torch's `fused=True` AdamW kernel (the thing that actually needs
sm_70+), so there's nothing to work around. Full writeup, including the
honest tradeoffs (no per-element adaptive LR, more LR tuning than
AdamW typically needed) and a documented CUDA-graph-capture caveat for
`grad_accum_steps`/`grad_scaler`/`skip_on_nonfinite`: see wiki
[Pressure Cooker V6 / V6V](Pressure-Cooker-V6.md).

✨ **V6 production-hardening pass** — `grad_accum_steps` and
`torch.cuda.amp.GradScaler` integration, same contract as
`pressure_cooker.InductionCooker` (`unscale_` → skip cleanly on
non-finite instead of corrupting momentum state → `update()`), plus an
opt-in `skip_on_nonfinite` for plain (non-scaler) training. The
non-finite check itself is batched into a single `torch._foreach_norm`
+ one host sync for the *whole step*, improving on `InductionCooker`'s
own per-parameter `.all()` sync rather than just copying it. Off by
default (`skip_on_nonfinite=False`) so the default configuration's op
count — and the CPU benchmark numbers above — are exactly what's
documented, not inflated by an always-on check most stable runs never
trip. `PressureCookerV6V` shares all of this through a new
`_apply_update()` hook instead of duplicating `step()`'s
accumulation/GradScaler/grad-clip logic a second time.

🐛 **CUDA graph capture + dynamic V6 features don't mix safely — now
documented, not silently wrong.** CUDA graphs bake in whichever
Python-level branch ran during `warmup_graph`, permanently: replay
always re-executes the same recorded kernels regardless of what later
batches look like. If `grad_accum_steps > 1`, `grad_scaler` is set, or
`skip_on_nonfinite=True`, the accumulation-gate / non-finite-skip
decision only gets evaluated once, at capture time.
`PressureCookerV6V.warmup_graph` now detects this configuration and
warns; the docstring spells out the mechanism and what to do instead
(don't graph-capture with those features enabled, or capture only once
the always-taken branch is known to be safe to repeat unconditionally).

🔧 **`tests/test_pressure_cooker_v6.py`** — new, real test coverage (not
a stub): construction/config, loss actually decreasing under several
configurations (nesterov, no-trust-ratio, no-foreach), fused vs.
non-fused paths producing numerically identical trajectories, weight
decay applying under a zero gradient, multi-param-group support,
state-dict round-tripping, optimizer-state byte count vs. AdamW,
gradient accumulation gating, GradScaler skip/apply/momentum-untouched
behavior, `skip_on_nonfinite` on and off, and — deliberately not just a
toy `nn.Linear` stack — a small transformer block (token embedding +
multi-head attention + LayerNorm + GELU MLP + output head) to confirm
V6 handles realistic parameter-shape heterogeneity. `PressureCookerV6V`
CUDA-only paths (construction on real CUDA tensors, graph capture, a
compiled step actually executing on a GPU) are marked
`skipif(not torch.cuda.is_available())` and were not exercised on real
CUDA hardware while writing this — this environment has no GPU. That
code reuses `ProCooker`'s already-shipped `warmup_graph`/`replay_graph`
implementation verbatim rather than inventing a new one, which is the
best available substitute for hardware verification, not a replacement
for it — stated plainly in the V6 wiki page too.

🔧 **`scripts/benchmark_v6.py`** (new) and
**`scripts/measure_optimizer_memory.py`** (extended) — real measurement
tools cited above, not hand-typed numbers. Both auto-detect CUDA and
report whichever device they actually ran on; `benchmark_v6.py` prints
an explicit note when it falls back to CPU rather than letting a CPU
number pass silently as if it were representative of GPU performance.

📚 **`hypernix.__init__` / `wiki_cli.py`** — `PressureCookerV6` and
`PressureCookerV6V` wired into the top-level lazy-import system
(`__all__`, `_LAZY_ATTRS`, the `TYPE_CHECKING` import block) and into
`hnx-wiki`'s module→page map, matching how every prior generation is
exposed — `import hypernix; hypernix.PressureCookerV6` works, and
`hnx-wiki` correctly resolves both new modules to the new wiki page.

📚 **`wiki/Pressure-Cooker-V6.md`** (new), **`wiki/Optimizers.md`**,
**`wiki/Home.md`** — new dedicated page for V6/V6V with the measured
numbers, usage examples, and the CUDA-graph caveat above.
`Optimizers.md`'s intro also got a small accuracy fix while touching
this page: it previously called V4 "the newest `OptimizerBase`-powered
line", which stopped being true once V5/V5S shipped and is now doubly
wrong with V6 added — it now points to both dedicated pages instead of
asserting a staleness-prone "newest" claim.

🛜 **Docs site: full holiday/observance calendar.** Extended the
existing Christmas / Christmas Eve / Halloween / Thanksgiving / July
4th / Pride Month banner system (`getActiveSiteEvent`/`EventBanner` in
`docs/src/App.tsx`) with 14 more: Trans Day of Visibility (Mar 31),
Transgender Day of Remembrance (Nov 20), MLK Day, Valentine's Day,
International Women's Day, St. Patrick's Day, Earth Day, Cinco de Mayo,
Memorial Day, Juneteenth, Bisexual Visibility Day, Labor Day, National
Coming Out Day, and New Year's Eve — each with its own hand-drawn SVG
icon and correct date logic, including two new date helpers
(`nthWeekdayOfMonth` already existed; added `lastWeekdayOfMonth` for
Memorial Day) rather than hardcoded dates for the floating holidays.
Juneteenth is checked ahead of the existing "any day in June is Pride
Month" catch-all so it gets its own banner on the 19th instead of being
silently shadowed. `MODULES` and the `WIKI_PAGES` fallback list also
updated for `pressure_cooker_v6`/`pressure_cooker_v6v` and the new wiki
page — `npm run build` verified clean after all of the above.


- `wiki/CLI.md` documented 13 of the CLI's 34 real subcommands and
  claimed that was the complete set. Added full sections for `brew`,
  `pipeline`, `assistant`, `cli`, `tvtop`, `cctvtop`, `fizzle`/`fiz`,
  `camo`/`camouflage`, `prot`/`protect`, `net`, `wiki`, `vera`,
  `scavenger`, `config`, `gkey`, `map`, `websearch`, `stml`. Fixed the
  companion-scripts list (was missing `multilama`, `gkey`, `hnx-map`,
  `tvtop-old`, `tvtop-older`, `hypernix-quantize`).
- 🐛 The docs site's (`docs/src/App.tsx`) "API Reference" tab was worse
  than stale — cross-checking it against the real source with an AST
  parser showed most of the listed functions (`download_snapshot`,
  `resolve_short_name`, `Session.add`, `EMA.update`, etc.) don't exist
  anywhere in the codebase, and only 36 of ~100 real modules were listed
  at all. Regenerated the whole `MODULES` array from real AST-parsed
  source instead of by hand — 99 modules, ~880 real signatures, so
  everything on the page now traces to an actual function. Also caught
  and fixed a splice bug of my own during that regen that had deleted
  the `WIKI_PAGES` fallback array entirely — caught by running a real
  `vite build` before calling it done, not just eyeballing the diff.
- 🐛 The docs site's `CLI_COMMANDS` array listed `hypernix complete` and
  `hypernix eval`, neither of which exist, and had wrong flags for
  `convert`/`quantize` (invented `--repo-id`/`--quants` args that don't
  match the real argparse definitions). Rebuilt from the real subcommand
  set; added the previously-undocumented "Companion console scripts"
  section.
- 🐛 **License was misrepresented on the docs site** — two hardcoded
  "Licensed under Apache-2.0" strings, despite `LICENSE` being a custom
  dual license (LLU-0.1 / HOS-1.0). Fixed there and in the README, which
  previously just said "LLU-0.1" with no mention of the HOS-1.0 option.
- 🐛 `pipeline` and `assistant` accept `--llm`/`--model` flags that are
  silently ignored — both call a hardcoded stub responder, not the model
  you pass. This isn't new in this pass, but it wasn't documented
  anywhere either; now flagged explicitly in `CLI.md` and the docs site
  instead of implying full inference support.
- 🐛 `wiki_cli.py`'s own `--help` text told users to invoke it as bare
  `hnx <module>`; it's only reachable as `hnx wiki <module>` (a
  subcommand of the main CLI). Also fixed the actual bug behind that:
  bare `hnx wiki` with zero arguments printed the `--help` block instead
  of the table of contents the help text itself claims is the default —
  the TOC branch existed in the code but was unreachable.
- 📚 `wiki/Home.md`'s "Topic guides" index only linked 19 of the 55 pages
  that exist; the other 36 were only reachable if you already knew the
  filename. Rebuilt the index to cover everything, grouped by theme.
- ✨ New page: [`wiki/HuggingFace-Models.md`](HuggingFace-Models.md) —
  catalogs all 54 models currently published under the `ray0rf1re` HF
  account, grouped by family, with short-name cross-references into
  `hypernix.download.KNOWN_MODELS` where they exist.

Scope note: this pass covered the CLI reference, the docs site, this
wiki's index, and the license text. It did not attempt to line-edit
every one of the ~50 per-module wiki pages against source — those were
spot-checked, not exhaustively re-verified.

## 0.71.4-3
✂️ removed the web ui due to it being full of lies and incomplete information and features 

## 0.71.4b10

✨ **Public release workflow: accurate "commits since" for stable releases** — `public-release.yml` used `git describe --tags --abbrev=0` to find the changelog baseline, which returns the *immediately preceding* tag regardless of whether it was a prerelease. Cutting a stable release after several betas (e.g. v0.71.4b6 → b7 → b8 → b9 → stable) meant the changelog only showed commits since the last beta, not everything that actually shipped since the last stable version. New "Determine changelog baseline" step: when the release being cut is stable, it walks tags version-sorted (`--sort=-v:refname`, not creation-date) and picks the most recent one that doesn't match the same prerelease-marker pattern the classify step already uses, skipping over any betas in between. Prereleases keep the old "since the immediately preceding tag" behavior — an incremental changelog per beta, not a re-diff against the last stable release every time. Verified against a constructed git history (stable → 3 betas → cutting a new stable) before merging, not just read over.

🐛 **README / PyPI page fixes** — The `hypernix.freezer` row claimed "16 CPU presets (i7 7th-14th gen, Core Ultra, Ryzen)"; the actual count was 48 (an earlier 32-preset addition was never reflected here) and there were zero Ryzen presets despite the claim — confirmed by grepping `CPU_PRESETS` directly, not just trusting the text. `hypernix.brewer` (the whole `hyperNx0x-v2` preset-family module) had no README row at all. Both fixed; module count bumped 11→12. Same staleness existed in `wiki/Alarms.md`'s CPU presets table (also missing i5/i9 entirely) and the GitHub Pages docs site's `SUBSYSTEMS` list (missing `brewer` and the entire hyped-pro module family) — all brought in sync, and the docs site's `vite build` verified clean after.

✨ **60 CPU presets, both meanings of "CPU preset" in this codebase** — `hypernix.freezer.CPU_PRESETS` gains 12 real AMD Ryzen entries (5000/7000/9000 series desktop, Zen 3/4/5) with verified specs (cores/threads/base clock researched per-SKU, not estimated) plus generational aliases (`ryzen-9000`, `ryzen-7-7000`, etc.), closing the README gap above. Separately, `hypernix.brewer` gains three CPU-*sized* architecture presets — `cpu-nano` (2,073,728 params), `cpu-tiny` (9,211,136 params), `cpu-small` (26,450,304 params), all measured via `BrewerModel.num_params()` rather than estimated, plain MHA with no sliding window for simplicity, positioned below the existing GPU-oriented `33m`/`micro`/`small`/`medium`/`large` family.

✨ **Real test coverage for everything shipped since 0.71.4b6** — None of `hyped_pro_core`, `hyped_pro_tools`, `multilama`, `hyped_pro_bridge`, or the interpreter-resolution launcher fix had pytest coverage; all of it was validated only through manual scripts during development. 125 new tests across 6 files: catalog integrity and both cloud dispatch protocols (mocked HTTP) plus the full agentic tool-calling loop for `hyped_pro_core`; real file-tool behavior and workspace path-traversal blocking for `hyped_pro_tools`; backend registry and GitHub-release asset-picking logic for `multilama`; the stdio JSON protocol for `hyped_pro_bridge`; provider-key storage round-trips for `config`; and the interpreter-resolution probing order plus the actual `HYPED_PRO_PYTHON` subprocess-env bug fix for the launcher. Along the way, found and fixed a real test-isolation bug of my own: `hypernix.config`'s `_CONFIG_DIR`/`_CONFIG_FILE` are resolved from `Path.home()` once at import time, so monkeypatching `HOME` after import silently does nothing — tests need to patch those module attributes directly instead. 1600 total tests pass (was 1475).

## 0.71.4b9

🐛 **More catalog fixes** — `qwable-3.6-27b-mtp` (Mia-AiLab/Qwable-3.6-27b-MTP) wasn't just wrong format (safetensors → gguf) — the community has reported llama.cpp failing to load it entirely ("missing tensor 'blk.64.attn_norm.weight'") and the repo owner's own comment confirms it was mid-fix, not stable. Swapped to the same publisher's plain (non-MTP) `Qwable-3.6-27b`, a single clean GGUF file with no such reports; renamed the catalog entry to `qwable-3.6-27b` to match. `qwable-9b-fable5` (empero-ai/Qwable-9B-Claude-Fable-5, safetensors) was auditing-caught before a bug report: its base, Qwen3.5-9B, uses a hybrid Gated-DeltaNet/full-attention architecture neither `HyperNixModel` nor the installed `transformers` recognizes — the same "falls back to HyperNixModel, may produce garbage" trap already confirmed live on `qwopus-3.5-9b-v3`. Swapped to the same publisher's official GGUF. `qwopus-3.6-27b-coder` and `qwopus-3.5-9b-v3` are confirmed genuinely safetensors (not broken/fake) but carry the same unrecognized `qwen3_5`/`qwen3_6` tag — flagged honestly in their catalog notes rather than swapped, since I don't have enough confidence in an alternative to recommend one.

🐛 **Fixed a double-period/jammed-text bug** in the wrapped multilama error message (`hyped_pro_core`'s GGUF-load error appended `". "` after a message that already ended in a period, and ran straight into the model's catalog notes with no separator).

🐛 **The footer box no longer disappears during local model loads/downloads** — `eraseFooter()` was wiping it to blank space the instant a noisy operation (download, local model load, tool-call execution) started, which looked like the banner vanishing; it wasn't scrolling away, it was being erased. New `settleFooter()` leaves it visibly on screen and just moves the cursor past it, so real backend output appends below and scrolls normally like anything else in the terminal, the same as everywhere else in this codebase that already prints real logs to the terminal.

✨ **New `Spinner` class** — a small, self-contained animated "thinking" indicator that only ever touches its own single line via `\r` + erase-to-end-of-line, never the footer engine's multi-line cursor math. That's what makes it safe to run during a noisy operation where the Python bridge is also printing its own real output on other lines at the same time — the old design used a live full-box redraw for quiet (pure network) turns and a static, non-animated message for noisy ones; now every chat turn gets the same real animated spinner regardless of backend.

✨ **`/settings thinking-display`** replaces the old `hide-thinking` boolean with five modes: `hidden` (default, unchanged), `grayed`, `normal`, `red`, `theme` (the active theme's accent color). `hyped_pro_core.send_chat_message` now returns `{content, thinking}` instead of a bare string — when thinking isn't hidden, `extract_thinking()` captures it instead of discarding it (built on the same tag-matching as `strip_thinking`, including the truncated/unclosed-tag case), so the TUI has real content to render in the chosen color before the main reply, printed as a separate `thinking>` line.

## 0.71.4b8

🐛 **Nanbeige fix** — `nanbeige4.2-3b-gguf`'s filename had the wrong case (`nanbeige4.2-3b-Q4_K_M.gguf` vs the repo's actual `Nanbeige4.2-3B-Q4_K_M.gguf`, a 404), and — the bigger issue — it was wired to the `vanilla` backend when Nanbeige4.2 uses a looped-transformer architecture (`general.architecture=nanbeige`) not in upstream llama.cpp at all, confirmed on the model card. Fixed the filename and added a `nanbeige` backend to `hypernix.multilama` (`Nanbeige/llama.cpp` @ `nanbeige42` branch, no prebuilt releases — same treatment as `prismml`).

✨ **Python interpreter resolution** — On a machine with more than one Python (pyenv/uv/conda alongside system `python3`), the bridge/GUI subprocesses could end up on a different interpreter than the one `hypernix` was actually installed into. Fixed at the root: `hypernix.hyped_pro`'s launcher now passes `HYPED_PRO_PYTHON=sys.executable` to the Node process it spawns (previously only *implied* in a debug message, never actually set — the real bug). For the case where hyped_pro.py itself is run by an interpreter without hypernix, `resolve_python_for_subprocess()` probes `python3.12` → `python3.14` → any other `python3.x` on `$PATH` with hypernix importable. The same probing is mirrored in `bin/_hypernix_python.sh` (shared by `bin/hyped-pro`/`bin/hyped-pro-gui`) and in `hyped_pro.ts`'s `pythonBin()`, so all three entry points agree regardless of how hyped-pro ends up being launched.

✨ **Hidden thinking output** — `hypernix.hyped_pro_core.strip_thinking()` removes inline `<think>`/`<thinking>`/`<reasoning>` blocks (Qwen3 thinking mode, DeepSeek-R1-style reasoners) from every reply, cloud or local, applied centrally in `send_chat_message` — including the truncated case where `max_tokens` cut generation off mid-thought (an unclosed tag), which now surfaces a short note instead of returning what would otherwise look like a silently empty reply. Toggle with `/settings hide-thinking on|off`.

✨ **`/settings`** — `max-input-tokens` (oldest turns trimmed before a turn is sent once the len/4 estimate exceeds it), `max-output-tokens` (real `max_tokens` on every backend), `max-thinking-tokens` (wired to Anthropic's real extended-thinking `budget_tokens` — the only backend with a native token-capped thinking budget; honestly labeled as having no effect elsewhere rather than pretending), and `hide-thinking`. All persisted to `~/.hyped-plus/config.json`.

✨ **Real file tools** — New `hypernix.hyped_pro_tools` module: `create_file`, `edit_file` (str_replace-style — exact, unique match required), `read_file`, `list_directory`, `search_files` (regex content search or filename glob). Every path is resolved and checked against a workspace root (`HYPED_PRO_WORKSPACE`, default the directory hyped-pro was launched from) before anything touches disk — a path that would escape it is refused. Wired into a real agentic tool-calling loop in `send_cloud_chat` (Anthropic's `tool_use`/`tool_result` blocks and the OpenAI-compatible `tool_calls` shape both handled — DashScope/Qwen and Moonshot/Kimi get this for free since they're OpenAI-compatible) and `send_local_chat_gguf` (via `multilama`'s new `chat_message()`, which returns the raw tool-call-capable message instead of just text — best-effort, depends on the GGUF's own chat template actually supporting function calling). Bounded at 8 rounds by default so a model that keeps calling tools without ever answering fails cleanly instead of looping forever. Every tool call and its result prints to the terminal as it happens — never silent. `hypernix.old_oven` (the plain safetensors path) has no tool-calling infrastructure, so tools simply aren't offered there rather than faking support. Toggle with `/tools on|off`; on by default.

## 0.71.4b7

✨ **New module: `hypernix.multilama`** — Unified interface over several llama.cpp variants, since one GGUF-publishing fork doesn't necessarily load on another's binaries. Backends: `vanilla` (upstream ggml-org/llama.cpp via the existing `llama-cpp-python` in-process bindings), `ik` (ikawrakow/ik_llama.cpp — newer SOTA quant types, faster MoE offload), `prismml` (PrismML-Eng/llama.cpp — the custom Q1_0_g128 1-bit hybrid-attention kernels `bonsai-27b-gguf` needs and no one else ships), `kobold` (LostRuins/koboldcpp). `vanilla` runs in-process; the fork-based backends have no Python bindings, so `multilama` fetches/caches their `llama-server`-style binary (generalizing `hypernix.fetcher`'s proven GitHub-release-asset logic to an arbitrary repo/binary name), launches it as a local subprocess, and talks to it over the same OpenAI-compatible HTTP protocol every llama.cpp-derived server exposes — the caller's `MultiLlama.chat()` call is identical regardless of which fork actually answered. GGUF files are always resolved to a local path via `huggingface_hub` before any backend launches, rather than relying on each fork's own (version-dependent) `-hf` convenience flag — `ik_llama.cpp` diverged from upstream in Aug 2024, before that flag existed there. `prismml` has no known prebuilt releases; calling it raises with the exact build-from-source command instead of guessing at a release asset. `python -m hypernix.multilama list` reports live availability per backend; `hypernix.hyped_pro_core`'s GGUF dispatch now routes through `multilama` instead of calling `llama_cpp` directly, so `bonsai-27b-gguf` goes from "will likely fail here" to "works once the fork is built."

## 0.71.4b6

✨ **`hyped+`/`hyped-pro` real provider dispatch** — Replaced the mocked chat reply with real dispatch through a shared Python layer (`hypernix.hyped_pro_core`, called from the Node TUI via a persistent `hypernix.hyped_pro_bridge` worker): real Anthropic Messages / OpenAI-compatible HTTP calls for cloud models, real local inference via `hypernix.old_oven` for HuggingFace models, and the real HNX1 Gatekeeper/Keymaster quota layer for T1. A failed call now surfaces a coded error (`HPC-*`/`HPB-*`/`HPT-*`) instead of a fabricated reply.

🛡️ **Provider reclassification** — Qwen (`qwen3.7-plus`) and Kimi K3 (`kimi-k3`) are now correctly classified as `cloud`, routed to Alibaba Cloud Model Studio (DashScope, OpenAI-compatible) and Moonshot AI respectively, each with a real, documented API base URL and auth env var (`DASHSCOPE_API_KEY`, `MOONSHOT_API_KEY`). Kimi K2.7 Code stays `local` (open-weight, self-hostable) since only K3 is cloud-only at launch.

✨ **Automatic local model downloads** — Selecting a `local` model (via `/model` or the model picker) or running `/download [model]` now auto-fetches its HuggingFace snapshot through the existing `hypernix.download.download_model` fallback-chain machinery if it isn't cached yet, with live progress on the terminal.

✨ **`/gui` desktop mode** — New `hyped-pro-gui` entry point (also reachable from the TUI via `/gui`) launches a real Qt6 desktop app (`PySide6`, working on both X11 and Wayland from one codebase) with a GTK4 fallback for Qt-less systems. Both backends log coded debug/error info to the terminal (`HPG-*` codes) and neither fabricates a chat reply — they call into the same `hyped_pro_core` dispatch as the TUI.

✨ **Real `/key` persistence** — `/key <vendor> <api-key>` now saves to `~/.hypernix/config.json` (via new `hypernix.config.get_provider_key`/`set_provider_key`) and is usable immediately without a restart; `/key` with no args shows masked status for every configured vendor.

🛡️ **Branding cleanup** — Removed the OpenClaw-inspired naming/theme references from `hyped+`'s banner, system prompt, and footer; it's its own design now. Docs updated to match (historical changelog/roadmap entries describing what actually shipped in `0.71.4b2` are left as-is).

🐛 **Fixes** — Added the `tsconfig.json` that `package.json`'s `build` script referenced but never shipped (the TS build was broken). Removed leftover joke debug comments from `hyped_pro.py`'s launcher in favor of a real `--debug`/`HYPED_PRO_DEBUG` flag. Fixed a broken-pipe traceback when quitting `hyped+` while a bridge request was still in flight.

🐛 **Real-world follow-up fixes** — A local-model chat turn on a model still loading for the first time could stack duplicate footer boxes on screen: the Python bridge's inherited stderr (transformers/torch warnings during model load) isn't coordinated with the TUI's footer redraw math, and racing a periodic spinner-redraw against it corrupted the terminal. `hyped_pro.ts` now suspends the live redraw for local/T1 turns and lets that output scroll normally, matching how `/download` already handled it. Separately, `hypernix.train.HyperNixConfig`/`load_snapshot` could silently build a model at its own dataclass defaults (vocab_size=32000, hidden_size=1024) when a downloaded checkpoint's `config.json` didn't use HF-standard field names, surfacing a cryptic `load_state_dict` size-mismatch deep in PyTorch instead of a clear error; `load_snapshot` now validates the real checkpoint's shape fields up front (with a `text_config`-nesting unwrap for wrapped/multimodal configs) and fails with the actual raw config keys shown, so a genuine schema mismatch is immediately diagnosable. A missing `huggingface_hub`/`torch` for whichever Python interpreter is actually running the bridge (common on machines with multiple Pythons — pyenv/uv/conda alongside system python3) used to surface as a bare `ModuleNotFoundError` traceback; it's now a coded `HPC-DEPS-001` error naming the exact interpreter in use and pointing at `HYPED_PRO_PYTHON` if that's not the one with the package installed. Selecting a local model and immediately running `/download` could race two concurrent downloads of the same model; concurrent callers now share one in-flight download.

✨ **GGUF model support** — `ModelDef` gained a `format` field (`"safetensors"` default, or `"gguf"`) and `send_chat_message`/`ensure_downloaded`/`is_downloaded` now branch on it, routing GGUF models through `llama-cpp-python` (`llama_cpp.Llama.from_pretrained` + `create_chat_completion`) instead of `hypernix.old_oven`/transformers — the same optional dependency HyperNix already ships for *producing* GGUFs (`hypernix[llama-cpp]`), now also used to *run* one. Added `qwen3-4b-gguf` (Qwen/Qwen3-4B-GGUF, Q4_K_M, 2.5GB), `nanbeige4.2-3b-gguf` (owao/Nanbeige4.2-3B-GGUF, Q4_K_M, 2.57GB — both fit comfortably in 8GB VRAM), and `bonsai-27b-gguf` (prism-ml/Bonsai-27B-gguf — flagged in its notes as needing a custom PrismML llama.cpp fork with non-standard 1-bit kernels that stock llama-cpp-python doesn't ship, so it's listed but will likely fail to load here). Also fixed two *existing* catalog entries (`qwopus-3.6-35b-a3b-coder-mtp`, `qwopus-3.6-35b-a3b-v1-mtp`) that were GGUF-only repos mismarked as safetensors-loadable — they'd have failed outright. New `HYPED_PRO_GGUF_CTX`/`HYPED_PRO_GGUF_NGL` env vars control context size and GPU-layer offload; models too large to fully fit even at their smallest quant (both 35B-A3B MoE Qwopus entries, 17.2GB minimum) default to a conservative partial-offload split instead of attempting full GPU offload and OOMing.

## 0.71.4b2

✨ **`hyped+` (`hyped-pro`) Node.js TUI** — Standalone Node.js interactive CLI (`hyped+` / `hyped-pro`) featuring a locked multi-panel layout inspired by OpenClaw, Qwen Code CLI, Claude Desktop, and Claude CLI. Includes quick 2D pixel art coffee mascot startup animation, 256-color Hyped theme, and instant execution.

✨ **Updated Hyped Model Catalog** — Added Kimi K3 (`kimi-k3`), Claude Sonnet 4.6 (`claude-sonnet-4.6`), Claude Sonnet 5 (`claude-sonnet-5`), Claude Opus 4.8 (`claude-opus-4.8`), Claude Haiku 4.5 (`claude-haiku-4.5`), Fable 5 (`fable-5`), GPT-4o (`gpt-4o`), GPT-5.6 Terra (`gpt-5.6-terra`), GPT-5.6 Sol (`gpt-5.6-sol`), GPT-5.5 (`gpt-5.5`), DeepSeek R1 (`deepseek-r1`), DeepSeek V4 Flash (`deekseek-v4flash`), Qwen 3.7 Plus (`qwen3.7-plus`), and Gemma 4 (`gemma-4-27b`).

✨ **Unified Model Directory & HF Token Support** — Standardized all model snapshot downloads, conversions, and caches across modules to a single unified path (`~/.hypernix/models` or `HYPERNIX_MODELS_DIR`). Added explicit HuggingFace token support (`hf_token` config setting / `HF_TOKEN` env var).

✨ **Hyped TUI Slash Commands & Features**:
  - `/system-prompt <text>`: Custom system prompt instruction support.
  - `/compact-prompt`: Prompt compactor tool to compress long custom system prompts into dense directives.
  - `/auto-compact`: Toggle automatic context window compaction.
  - `/price`: Real-time token count and USD price cost estimation per model.
  - `/vision <img> <prompt>`: Multi-modal vision input support.
  - Command auto-completion on tab for all slash commands.

✨ **Brewer 33.6429M Parameter Architecture** — Added `hypernix0x_v2_33m` (33.6429M parameters: 33,642,900 parameters) architecture preset (`d_model=512`, `n_layers=6`, `d_ff=1444`, `ctx=4096`) in `brewer.py`.

🐛 **Normal Hyped Model Load Error Fix** — Resolved issue where missing local model weights caused `hyped` to return `[Error: Model runner not properly loaded.]`. Improved exception handling, fallback logic, and auto-download prompts.

🛡️ **`hyper-Nix.2` Undertrained Warning Banner** — Prominently surfaces the undertrained warning box whenever `hyper-Nix.2` is selected or executed.



## 0.71.1

✨ **`hnx map`** — a new steampunk schematic TUI. Dials represent parameter
counts (per-layer, scaled by a configurable `acc` value), pipes represent
layer connections, animated steam represents live data flow, and steam
engines represent prompt/dataset input. A dedicated throttle dial sweeps
only while a training run is actually active (via `checkpoints/train.log`
telemetry). Detail level (`poly`: 16/32/64/128) scales dial resolution,
pipe-joint richness, and steam-animation frame count. Reads architecture
from a single `.safetensors` file, a full model folder (auto-discovering
sharded weights, or falling back to an analytical estimate from
`config.json` if no weights are present yet), or runs with just live
`train.log` telemetry and no architecture breakdown. Move the mouse into
the bottom-right corner for a legend (falls back to `?` on terminals
without mouse-motion reporting). Configured via `hnx map config poly|acc|
main use-gpu|main tps|main file model <1|2|3> [-f|-F PATH]`; see
`hnx map --help`.

✨ **`UniversalCooker` / `universal_cooker()` now default to the V5S
optimizer tier** instead of the legacy CPU/CUDA device tiers. Pass
`variant="v5"` / `"v5-plus"` / `"v5s"` (default) / `"legacy"` to choose;
a CUDA device detected as pre-Volta (Pascal, sm_61/6.2) still
auto-selects the matching `Aged*` tier (`Agedcookerv5`,
`ULTRAagedcookerv5`, `Agedcookerv5s`) exactly as the old device-tier
logic did for `InductionCooker`. `variant="legacy"` restores the
pre-0.71.1 selection behavior unchanged.

🐛 **Fixed corrupted borders in `tvtop++` and `cctvtop`.** The Hardware
Vitals / GPU Details panels' bar gauges and history graphs embedded raw
ANSI escape codes directly into Rich `Text` objects; Rich has no way to
know those bytes aren't visible characters, so its cell-width
measurement came out wrong and the panel's right-hand border got drawn
in the wrong column (stray "│" characters floating outside the box).
Fixed by routing that content through `Text.from_ansi` instead, which
parses the escape codes into proper zero-width style spans.

🔧 Internal: `pressure_cooker.py`'s `UniversalCooker` gained a
`_select_legacy` / `_select_v5_family` split; existing tests that
exercised the old default now pass `variant="legacy"` explicitly.



## 0.70.6-3

✨ **all imports are now lazy, speeding the intire package up.**



## 0.70.6

✨ **Pressure Cooker v5S.** Added new oscillation resistant cosin 3d, pressure diffusion low power optimizer `PressureCookerV5S`. It targets a 2.1x speedup over AdamW while using less RAM.
✨ **CLI Optimization.** Drastically improved CLI startup speed by deferring heavy PyTorch imports across all subcommands via an updated fast-path check.
✨ **Automated Release Timeline.** Added a GitHub Action step to automatically generate and append a Mermaid.js horizontal release timeline to the wiki on every public release.
✨ **New CLI Subcommands.** Added `wiki`, `vera`, `scavenger`, and `config` to the main `hnx` interface.
🐛 **Log Tailing Fixes.** Fixed `cctvtop` and `tvtop++` auto-detecting Chromium binary logs by aggressively filtering out `.config`, `.cache`, and non-text files.
🐛 **cctvtop VNC.** Fixed the VNC logic in `cctvtop` to correctly use the `$DISPLAY` variable and spawn `x11vnc` with `-shared`.
📚 **Documentation Updates.** Expanded the "Learn" page on the website and added new documentation and wikis for V5S, Vera, and Scavenger.

## 0.70.5b2

✨ **Net Module.** New `hypernix.net` module for distributed network operations and Tailscale integration. Features: `config`, `auto-setup`, `m-setup`, `connect`, `status`, `m-ip`, `a-il` (auto-connect), `mutli-a-port`, `ex-port`, `s-storage` (distributed storage sharing), `onef-all`, `tail acheck` (automatic Python script checks over Tailscale SSH), and `tail stop`. Accessible via `hnx net <cmd>`. Fully implemented using `subprocess` with `tailscale` and `ssh` commands without relying on mocked stubs.

✨ **Protect Module.** New `hypernix.protect` module for hardware health and monitor protection. Configurable via `hnx prot bind [set|reset] <word>`. Sleeps the monitor via `xset dpms force off` and uses raw terminal input modes to invisibly wait for the wake word (default: "bon") before waking the monitor via `xset dpms force on`.

🐛 **cctvtop Python Rewrite.** Completely rewrote the buggy C++ `cctvtop_ext` wrapper (`cctvtop.py`) into a pure Python 2D interface using `rich.live.Live` with `screen=True`. Fixes terminal scrolling artifacts, duplicate text, and lockups, cleanly tracking and rendering the latest `.log` file in a robust layout.

🛡️ **CLI Default Polish.** Running `hypernix` or `hnx` with no valid subcommand or just invalid flags now cleanly prints the usage menu instead of silently falling back to the legacy `all` (download -> convert -> quantize) pipeline.

## 0.70.5b1

✨ **Brewer Module.** New `hypernix.brewer` module for building fully custom transformer architectures from scratch with no base model. Features: `BrewerConfig` dataclass, `BrewerModel` (RMSNorm + RoPE + GQA + SwiGLU + optional sliding-window), the **hyperNix0x-v2** preset family (Small 9L/ctx=20482, Medium 18L/ctx=40964, Large 36L/ctx=103724), training loop with cosine LR schedule, PyTorch + GGUF export, auto-registration into `KNOWN_MODELS`, and full CLI via `hnx brew`.

✨ **WebUI Overhaul.** Complete rewrite of the web dashboard with in-depth controls for every HyperNix module: Training (PressureCookerV4 params), Brewer (architecture builder + registry), Camouflage (RLHF/RLAF config), Fizzle (model fusion), Download, Quantize (30+ quant types), Tupperware (round planner), Pans/Data Prep, Pressure Cooker (code gen), Abbicus (curriculum config), Hyper-Log (code gen), Upload, Ethanol (GPU controls), Script Builder (now exports Python), Network, and Settings. All panels generate real CLI snippets.

✨ **Autofix Scripts.** New standalone scripts in `scripts/`:
  - `autofix-B` — bash script for CI failures: runs `ruff --fix` + `--unsafe-fixes`, commits with `[autofix-B]` message.
  - `autofix-E` — Python script for public release failures: fixes dup imports, bare `except:`, `from __future__ import annotations` gaps, empty tests, type-checking guards, then `py_compile`-validates every file.

✨ **GitHub Actions — Python 3.14 + macOS M-series.** Updated `ci.yml` to test against Python 3.11/3.12/3.13/3.14 (`allow-prereleases` for 3.14) on `ubuntu-latest`, `ubuntu-22.04`, and `macos-latest` (Apple Silicon). Torch installs routed by OS.

🐛 **tvtop++ Border Artifacts Fixed.** Refactored `run()` to build the Rich `Layout` tree once and only call `.update()` on named slots each tick, eliminating ghost border artifacts from repeated full layout reconstruction.

✨ **tvtop++ All-Process Monitor.** `_get_active_processes` now shows the top 12 system-wide processes by CPU (all processes, not just python/train), adds a STATUS column, and uses a `show_all` toggle.

🐛 **Chromium Log Filter.** `_autodetect_log` in `tv.py` now skips any `.log` file with `chromium` or `chrome` in the name to prevent auto-tailing browser debug logs.

🔧 **CLI `brew` → Brewer.** `hnx brew` now routes to `brewer.cli_main` instead of `instant_pot.brew`.

## 0.70.5a2

✨ **Massive Model Support Expansion.** Added support for GLM 5.2, Nex-N2, more Nemo models, LFM 2.5, SmolLM 3, Z Image, all Whisper models, DeepSeekV4, Kimi K2.5+, more Gemma 4, more Qwen, and Mimo models. Added explicit support for "Model Families" grouping.
✨ **Camouflage (RLHF/RLAF).** Added a new module `hypernix.camouflage` with CLI support via `hnx camo`. Includes AI-assisted modes `-Ai` and full scaffolding for RLHF loops.
✨ **Fizzle Image Models.** `fizzle` now automatically supports Vision/Image models using `AutoImageProcessor` to construct multi-modal architectures seamlessly.
✨ **Hyper-Log TUI.** New premium dashboard (`hyper_log`) providing consistent, styled console logs for training with deep metrics: 5-decimal grad norm, learning rate, epoch progress, GPU telemetry, ETA, and emergency stop features.
✨ **Pressure Cooker V4 Enhancements.** Fleshed out quantization scaling stubs, added Sophia clipping approximation, and enhanced Pascal architectural warnings.
✨ **Spinner Consistency.** Brought the new `spinner` animations across `tvtop++`, `tvtop` (old), and `cctvtop`.
📚 **Documentation Updates.** Expanded GitHub Pages docs to highlight Camouflage and Hyper-Log, plus corresponding Wiki entries.

## 0.70.4b11

✨ **`qa` — Q&A dataset formatter.** New module (`hypernix.qa.QAProcessor`)
turns structured datasets (JSONL, lists of dicts, plain text files) into raw
text strings for causal LM training. Supports `question_answer` mode
(`Question: {q}\nAnswer: {a}`) and `predict_next` concatenation mode.
Optionally integrates with `salt_shaker` and `pepper_shaker` — seasoning is
applied to the raw fields *before* templating so the `Question:` / `Answer:`
keywords are never corrupted. Automatic key fallbacks handle `instruction` /
`completion` / `prompt` / `response` naming conventions.

✨ **`stml` — Short Term Memory Loss context manager.** New module
(`hypernix.stml`) with two components:
- **`calculate_vram_context`** — estimates the maximum safe trained context
  length from VRAM, model size, batch size, and precision. Returns a multiple
  of 128. Accessible via `hypernix stml --vram N --params N` CLI.
- **`STML`** — training-time context manager that enforces an `untrained_max_context`
  hard cap and folds long sequences into the batch dimension using
  `segment_length`-sized chunks `(batch × num_segments, segment_length)`,
  so the model trains on all the data rather than just a truncated slice.
  Accepts an optional `regulator` (`Abbicus` / `TurboAbbicus`) that is applied
  first. Compatible with `old_oven.CodeOven.train()` and `hypernix.train.train()`.

✨ **`TurboAbbicus` — exponential curriculum regulator.** New curriculum
class (`hypernix.abbicus.TurboAbbicus`) configured via `TurboAbbicusConfig`.
- **Exponential growth** — context grows as `base × exp(k × progress)` from
  25% of base to `hard_cap` (vs. linear Abbicus).
- **Configurable `hard_cap`** — absolute maximum context in tokens.
- **Sine-wave oscillation** — when the cap is reached, context oscillates
  around `hard_cap` using `sin(step × frequency) × amplitude`, adjusted by
  host CPU load. GPU utilisation is never used as a change factor.
- **VRAM safeguard** — on each `step()`, VRAM allocation is checked; if it
  exceeds `vram_safety_threshold` (default 90%), context is scaled back 10%.
  It recovers +5% per step when pressure eases.

✨ **`tvtop++` layout, color, and resize fixes.**
- Fixed a layout-tree bug where `layout["body"].split_column()` was called
  *after* a `split_row()`, causing border shifting on every refresh. The
  layout is now rebuilt as a clean static tree (`body → top/bottom → left/right`).
- Fixed hardware panel colors to match original `tvtop` (CPU=green,
  RAM=magenta, GPU=red; was all-default before).
- Fixed `Console` being created with a hardcoded `width=term_width` that
  prevented the dashboard from adapting when the terminal was resized.
- Made graph width and log-tail line width dynamic (scale with `console.width`).
- Log tail now shows 8 lines (was 6).

✨ **`hypernix stml` CLI subcommand.** New `hypernix stml` command exposes
`calculate_vram_context` from the shell with `--vram`, `--params`,
`--batch-size`, `--precision`, `--num-layers`, `--num-heads`, `--head-dim`.

✨ **`hypernix train run` curriculum flags.** Added `--use-abbicus`,
`--use-turbo-abbicus`, `--use-stml`, `--untrained-max-context`,
`--segment-length` to `hypernix train run`.

🔧 **Version bump.** `0.70.4b11`.

📚 **Documentation.** Updated `Abbicus.md` with full TurboAbbicus reference.
New `STML.md` wiki page. Added `qa` section to `Kitchen.md`. Updated `Home.md`.

🛡️ **59 new tests** in `tests/test_v0704b11_features.py` covering all new
modules, config classes, CLI integration, layout correctness, and train/oven
signatures. Tests are version-resilient (check APIs and behaviour, not
internal details).

---

## 0.70.5b2

✨ **Net Module.** New `hypernix.net` module for distributed network operations and Tailscale integration. Features: `config`, `auto-setup`, `m-setup`, `connect`, `status`, `m-ip`, `a-il` (auto-connect), `mutli-a-port`, `ex-port`, `s-storage` (distributed storage sharing), `onef-all`, `tail acheck` (automatic Python script checks over Tailscale SSH), and `tail stop`. Accessible via `hnx net <cmd>`. Fully implemented using `subprocess` with `tailscale` and `ssh` commands without relying on mocked stubs.

✨ **Protect Module.** New `hypernix.protect` module for hardware health and monitor protection. Configurable via `hnx prot bind [set|reset] <word>`. Sleeps the monitor via `xset dpms force off` and uses raw terminal input modes to invisibly wait for the wake word (default: "bon") before waking the monitor via `xset dpms force on`.

🐛 **cctvtop Python Rewrite.** Completely rewrote the buggy C++ `cctvtop_ext` wrapper (`cctvtop.py`) into a pure Python 2D interface using `rich.live.Live` with `screen=True`. Fixes terminal scrolling artifacts, duplicate text, and lockups, cleanly tracking and rendering the latest `.log` file in a robust layout.

🛡️ **CLI Default Polish.** Running `hypernix` or `hnx` with no valid subcommand or just invalid flags now cleanly prints the usage menu instead of silently falling back to the legacy `all` (download -> convert -> quantize) pipeline.

## 0.70.5b1

✨ **`hnx` CLI Shortcut.** Added a new CLI shortcut alias `hnx` which matches all capability of the main `hypernix` command.

✨ **`tvtop++` / `tvtoppp` Live Dashboard.** Created a premium, highly-styled console training monitor featuring rounded boxes, interactive spinning loaders, deep color palettes, a comprehensive **Process Monitor** panel (tracking python/training PIDs, CPU%, memory, and command names), and extended GPU telemetry.

✨ **Resilient Log Parser.** Overhauled the log parser (both for `tvtop` and `tvtop++`) to recursively check and parse irregular format log files (tqdm, JSON, Lightning) for loss (e.g. `loss=`, `loss:`), step count/fractions, learning rate, and throughput.

✨ **Asymptotic Loss Decay Curve.** Replaced simple linear extrapolation of loss predictions with a dampened exponential decay simulation that curves asymptotically, avoiding divergent loss lines.

✨ **Block-Style Hardware History.** Added color-coded Unicode density blocks (`░▒▓█`) representing hardware history for CPU, RAM, and GPU.

🛡️ **14 new tests.** Added tests for `lazy_suzan` (v0.70.3 additional tests) and the updated log parser, block history, loss curve estimations, and `tvtop++` dashboard.

🔧 **Version Bump.** Updated all version files across the package to `0.70.4b1`.

---

## 0.70.3b2

✨ **Web UI ground-up rebuild.** Replaced the monolithic inline HTML dashboard with a modular static frontend (`webui_static/`) served by a threaded HTTP server. Tailscale is now **opt-in only** via `-T` / `--tailscale`; local-only is the default. Fixed the `WebUIServer` constructor mismatch that broke CLI launches.

✨ **`Tupperware` — automated dataset round splitting.** New module splits a chosen dataset into N training rounds with automatic step budgets, per-round optimal LR (scale-aware heuristic), warmup/cooldown ratios, and optional evaluation at the end of each round. Integrates with `new_fridge.plot_round_losses` for multi-round loss charts.

✨ **`StovetopV3CookerPlus` (v0.70.3).** Pascal-safe V3Plus variant with forced sm_61 kernels, adaptive gradient clipping, EMA shadow weights, and optional QAT via `QuantConfig`.

✨ **`HyperNixQuantizer` — quantize facade.** Remade the quantize surface with use-case profiles (`chat`, `code`, `edge`, `quality`, `reference`), batch planning/runs, and a formatted catalog printer. Existing `quantize_gguf` / `CATALOG` API unchanged.

📚 **Wiki expansion.** Dedicated pages for Pressure Cooker v3, Abbicus, Frameworks, Tupperware, and a Roadmap (0.70.4 → 0.70.6 → 0.71.2). Updated Ovens, Fridges, and Home index.

🔧 **`old_fridge` / `old_oven` distributed unwrap.** `unwrap_model()` now peels DDP, FSDP, and DataParallel wrappers; `CodeOven.train` binds optimizers to the unwrapped core.

---

## 0.70.3

✨ **`lazy_suzan` — High-efficiency decentralized multi-GPU linking.** A new module allowing linking of multiple GPUs without a physical NVLink, utilizing fp8/int8/topk gradient compression, overlapped backward-pass communication, and a custom P2P ring topology to bypass standard NCCL bottlenecks.

✨ **`PressureCookerV3` Variants.** Added `StovetopV3Cooker` for safe backwards compatibility on older CUDA 6.1 (Pascal) hardware by disabling fused/foreach kernels. Added `CookerLite` for a heavily optimized CPU-only training loop. Aliased the legacy `peak_lr` parameter to the standard PyTorch `lr` naming convention.

🐛 **`ComputeFramework` Crash Fix.** Fixed string-based instantiation crashes in `instant_pot.py` when initializing `ComputeFramework`, and properly added `backward()` and `step()` bindings to allow seamless hookups with the `lazy_suzan` auto-synchronizer.

---

## 0.70.1

✨ **WebUI Design Rewrite.** Completely rebuilt the `webui.py` frontend using a premium glassmorphism aesthetic. Removed generic styles in favor of vibrant gradients, deep blurred backgrounds, dynamic hover animations, and a sleek dark mode. The UI now looks strictly modern and state-of-the-art.

✨ **`tvtop` Instant Boot & Hardware Telemetry.** `tvtop` now starts up instantly due to lazy loading heavy modules (`abbicus`, `train`) in `hypernix/__init__.py`. Added historical line-graphs (up to 120 ticks) for CPU, RAM, and GPU utilisation directly in the TUI. Added a predictive loss curve extending the current loss trajectory into the future for easy estimation of convergence. Fixed a parsing error with `nvidia-smi` on certain GPU names that broke VRAM stats.

✨ **`workshop` Conversational Streaming.** Rewrote the `ASRToLLMToTTS` pipeline in `workshop.py` to stream generator-based sentences for real-time conversational flow, heavily reducing time-to-first-audio-byte compared to the previous blocking implementation.

✨ **`instant_pot` Modernization.** The one-shot `brew()` trainer now gracefully supports `PressureCookerV3`, automatically regulates context windows with `Abbicus`, and implements multi-device distributions via `ComputeFramework`. Upgraded `old_oven` and `old_fridge` to support seamlessly unwrapping models bound to FSDP/DDP topologies.

🐛 **`PressureCookerV3` LR Floor Fix.** Added a `1e-6` minimum floor to the scheduled learning rate drop to prevent catastrophic model collapse or stalled training when the LR scheduler zeroes out near the end of the steps.

🛡️ **Mixed-Precision Test Suite.** Vastly expanded unit testing in `tests/` specifically benchmarking `PressureCookerV3` memory savings across FP8, FP64, Q5.5, and Q4M variants vs `AdamW`.

---

## 0.70.0

✨ **`abbicus` — Automatic token regulation and curriculum tuning.** New
module that dynamically modifies max sequence length and token
padding/truncation strategies during training based on model size,
context length, dataset complexity, and current global step. Supports
model sizes from 0.5B to 72B with automatic size-based multipliers.
Configurable curriculum steps, dynamic padding, and dataset-type
awareness.

✨ **`compute_framework` — Hardware-agnostic multi-device training.**
Abstracts away CUDA, MPS, CPU, and TPU backends with automatic DDP /
ZeRO wrapping. `ComputeFramework` class handles PyTorch DDP
initialization, device placement, and fallback logic automatically.
Supports distributed training with `local_rank`, `world_size`, `use_ddp`,
`use_fsdp`, and `zero_stage` parameters. Auto-detects available compute
backend and sets up the appropriate device.

✨ **`pressure_cooker` V2 rewrite — Quantization-aware training.** Full
V2 implementation with fp16/bf16/fp64 mixed-precision, automatic dtype
detection, and quantization-aware training (QAT) hooks for Q8/Q6/Q5.5/Q4M.
10 major upgrades: gradient checkpointing integration, adaptive gradient
clipping with per-layer scaling, EMA weight shadowing, distributed
training awareness (DDP/FSDP compatible), dynamic loss scaling with
backoff on overflow, parameter freezing/unfreezing callbacks, learning
rate finder utility, and training metrics streaming to tvtop dashboard.
Device-specific tiers (`StovetopCooker`, `ElectricCooker`,
`InductionCooker`, `ProCooker`) all upgraded to V2 standards.

✨ **`pressure_cooker_v3` — ZeRO-optimized V3 optimizer.** Replaces V2
with full ZeRO-1/2 optimizations, FP8 support, and zero bugs. New
`QuantDtype` enum (FP8/FP16/FP32/FP64/Q8/Q6/Q5_5/Q4M) and `QuantConfig`
dataclass for fine-grained quantization control. `PressureCookerV3`
class with advanced ZeRO stage support, improved memory efficiency, and
heavily tested quantization paths.

✨ **`workshop` — Model frameworks and TTS/ASR pipelines.** New room for
building model frameworks with pre-built templates for TTS, ASR, LLM,
and Vision models. `WorkshopFramework` base class with
`FrameworkConfig` dataclass. Full compatibility with
ray0rf1re/nano-nano collection and 30+ additional architectures including
LiquidAI LFM2.5, MiniCPM5, Gemma 4 family, Qwen3.5 series, Phi-4,
DeepSeek-V2.5, GLM-Edge/MoE, GPT-OSS, Nemotron, Llama-3.2, Mistral-Nemo,
Mixtral-8x22B. Includes `TTSEngine`, `ASREngine`, `ASRToTTS` (direct
speech-to-speech), and `ASRToLLMToTTS` (full conversational pipeline).

🔧 **`tvtop` backwards-compatibility shim.** All tvtop functionality
moved to `hypernix.tv`; this module now re-exports everything so
`import hypernix.tvtop` continues to work. Console script `tvtop` still
registered and points at `hypernix.tv.cli_main`.

📚 **Documentation updates.** Wiki expanded with usage examples for all
new modules. README updated with v0.70.0 feature highlights.

---

## 0.61.4

🖥️ **`tvtop` btop-style multi-panel rewrite.**  Reported on a
mid-screen rendering: the 0.61.1 dashboard "still sucks and only
shows CPU usage" — the single ``hardware`` panel was visually
sparse compared to btop++'s rich CPU / memory / GPU breakdown.

The 0.61.2 dashboard splits the old single ``hardware`` panel
into **four** richer panels in a 2×2 grid above the loss curve +
log:

* **`cpu` panel** — TOTAL utilisation bar at the top, then a
  **per-core grid** in two columns (each cell ``cN <bar>
  NN.N%``), then a 3-row history graph rendered through the
  same multi-row block-bar helper used for the loss curve.
  Per-core sampling: ``psutil.cpu_percent(interval=None,
  percpu=True)`` first, then a Linux-only ``/proc/stat`` per-CPU
  fallback that reads each ``cpuN`` line and computes the
  delta-against-prev sample.
* **`memory` panel** — separate bars for ``USED`` /  ``CACHE``
  / ``FREE`` / ``SWAP`` (each with absolute MiB), plus a 2-row
  history graph.  Sourced from
  ``psutil.virtual_memory()`` + ``psutil.swap_memory()`` first,
  then ``/proc/meminfo`` (``MemTotal`` / ``MemAvailable`` /
  ``Cached`` / ``SwapTotal`` / ``SwapFree``) on Linux.
* **`gpu` panel** — GPU name on top, then ``UTIL`` / ``VRAM``
  (with ``used/total MiB``) / ``TEMP`` (mapped 30-100°C across
  the bar so a hot GPU is visible) / ``PWR`` (against
  ``power.limit`` so 100% bar = at TDP) gauges + 2-row util
  history.  Falls back to a clean ``(no GPU detected)``
  placeholder when ``nvidia-smi`` isn't on PATH.
* **`training` panel** — unchanged from 0.61.1.

The footer now shows ``cores=N · gpu=<name>`` so users can see
at a glance whether the new probes resolved.

🔧 **New probes in `hypernix.tv`**:
* ``_safe_psutil_per_core()`` — per-core list of CPU
  percentages, ``None`` if psutil isn't installed.
* ``_read_proc_stat_per_core()`` — Linux fallback that needs
  two consecutive samples to compute deltas (returns ``None``
  on the first call).
* ``_read_memory_breakdown()`` — dict of
  ``total_mib`` / ``used_mib`` / ``free_mib`` / ``cached_mib``
  / ``swap_used_mib`` / ``swap_total_mib`` / ``percent``.
* ``_query_nvidia_smi_full()`` — extended ``nvidia-smi`` query
  that returns name + temperature + power.draw + power.limit
  alongside the original mem/util tuple.  Cached for 3 s
  alongside the legacy 3-tuple.
* Rolling history deques (``_cpu_history``, ``_ram_history``,
  ``_gpu_util_history``) capped at 120 entries, populated each
  ``latest_frame()``.

🪪 **No btop code was copied.**  The dashboard is original
Python that mimics the same UX patterns (per-core grid, time-
series block graphs, coloured threshold bars).  btop++ is
GPL-3.0 C++ source and reproducing it into hypernix would be a
license/copyright problem — so this is a clean-room
implementation inspired by the same look-and-feel.

🛡️ **9 new regression tests** in ``tests/test_v061_2.py``
covering: ``_read_memory_breakdown`` shape, ``_safe_psutil_per_core``
return type, ``/proc/stat`` per-core delta semantics, per-core
grid label appears in render, memory panel renders breakdown or
fallback, GPU panel renders gauges or no-GPU placeholder, footer
shows core count + GPU label, CPU/RAM/GPU history deques grow
per frame and are capped at 120.

The existing ``test_render_uses_panel_frames`` was updated to
check for the new ``cpu`` / ``memory`` / ``gpu`` panel titles
instead of the old single ``hardware`` title.

---

## 0.61.1

✨ **`hyped` chat CLI.**  New high-quality TUI chat CLI registered
as the ``hyped`` console script.  Two-screen flow:

1. **Configurator** — pick a model from the curated short-list
   organised by family (HyperNix / Nix / Qwen 3.5 / Nano), or
   ``0`` to browse every entry in :data:`KNOWN_MODELS`.  Pick a
   persona from :data:`hypernix.menu.MENU` (or ``0`` for none).
   Tweak sampling defaults (temperature / top_p / top_k /
   max_new_tokens) — press Enter on each to accept.
2. **Chat** — full-screen panel layout: status bar (model /
   persona / sampling), conversation panel with the last 12
   turns wrapped to terminal width, then a typing prompt.
   Streams tokens through :class:`hypernix.bell.Bell` and applies
   :class:`hypernix.flour.Flour` (smart by default; switch via
   ``--flour aggressive|off``).  Slash commands inside the chat:
   ``/quit``, ``/reset``, ``/persona <name>``, ``/save <path>``,
   ``/help``.

Skip the picker with ``hyped --model <short>``; pre-pick a
persona with ``hyped --persona <name>``.  ASCII fallback via
``hyped --ascii`` for non-UTF terminals; ``readline`` is loaded
when available so up-arrow recall + inline editing Just Work.

🚨 **MAJOR ``hyper-Nix.2`` undertrained warning.**  The chat-tuned
``ray0rf1re/hyper-Nix.2`` checkpoint shipped publicly but its
training run was cut short — outputs are often nonsensical,
repetitive, or incoherent.  ``hypernix.utils.warn_hyper_nix_2``
fires a red-bordered ANSI box on stderr the first time any
hyper-Nix.2 alias is touched (``download_model``, ``preheat``,
``hyped --model hyper-nix.2``).  Idempotent per process; suppress
with ``HYPERNIX_SUPPRESS_HYPERNIX2_WARNING=1``.  Also demotes the
hyped configurator badge from ``★`` to ``⚠`` and points users at
``Nix-ai/Nix-2.7a`` / ``Qwen/Qwen2.5-7B-Instruct`` /
``ray0rf1re/hyper-nix.1`` as solid alternatives.

🐛 **Five bug-fix passes** while building hyped:

* **hyped chat loop** now routes through ``Countertop.say()`` with
  a streaming token callback registered on the bell, instead of
  bypassing the countertop's history / trim / clean logic.
* **hyped ASCII picker** uses ``*`` instead of ``★`` for the
  default-model badge so non-UTF terminals don't render ``?``.
* **`ups.UPS` instantiation** is now lazy — IP-geolocation deferred
  to the first ``check()`` call, so ``UPS()`` no-args returns
  instantly instead of blocking on a 5-second HTTPS round-trip.
* **`plasma.calibrate_alarm`** stashes the pristine bound method
  on ``alarm._plasma_original`` and resets to it before
  re-wrapping, so calling ``calibrate_alarm`` twice no longer
  compounds factors.  New ``reset_calibration(alarm)`` undoes
  the wrapper entirely.
* **`tv._sanitise`** now exempts ``\r`` (0x0D) from the
  non-printable strip so Windows CRLF logs don't lose every line
  ending to ``?``.

🛠️ **Utility helpers** added:

* **`hypernix.utils`** (new module): ``healthcheck()`` /
  ``diagnostic_info()`` / ``list_models()`` / ``print_models()`` /
  ``session_dir()`` / ``is_module_available()`` /
  ``has_binary()``.  Diagnostic snapshot includes torch +
  CUDA + every common optional dep + relevant binaries on PATH +
  the ``KNOWN_MODELS`` count.
* **`Menu.find(query)`** — fuzzy persona lookup with exact /
  case-insensitive / substring / prefix matching.  Returns
  ``None`` on ambiguous matches so the caller can disambiguate.
* **`hypernix.injection.thinking()` / `testing()` /
  `system_override()`** — module-level shortcuts so
  ``injection.thinking("hi")`` works without instantiating an
  injector.

🔌 **New console script** in ``pyproject.toml``:
``hyped = "hypernix.hyped:cli_main"``.

🛡️ **37 new tests** in ``tests/test_v061_1.py`` covering every
bug-fix regression (ASCII picker / lazy UPS / plasma compounding /
CRLF / hyped curated short-list), every utility helper, every
fuzzy-find branch in ``Menu.find``, every injection shortcut, and
every code path of the hyper-Nix.2 warning (alias matching /
once-per-process / force re-emit / non-v2 skip / env-var
suppression).

---

## 0.61.0

🐍 **Python 3.14 support.**  ``requires-python`` bumped to
``>=3.10,<3.15``; classifiers gain
``Programming Language :: Python :: 3.14``.  No code changes
needed — every module imports clean on the 3.14 release
candidate.

✨ **Three new modules.**

* **`hypernix.ups`** — uninterruptible-power-supply mode.
  Checks two real-world signals every ``check_interval_seconds``
  (default 5 minutes):
    * **Weather** — open-meteo (free, no API key).  Forces a
      checkpoint when the WMO weather code is in
      :data:`SEVERE_WEATHER_CODES` (heavy rain 65/66/67, heavy
      snow 75, violent rain showers 82, thunderstorm 95/96/99).
    * **Scheduled outage** — pluggable
      ``outage_check_fn(address) -> bool`` callback so a user
      can wire in their utility's "scheduled maintenance" lookup.
  On a panic transition (was-clear → severe / outage), the UPS
  fires the user-supplied ``snapshot_fn`` exactly once, then
  shrinks ``save_every`` by ``cadence_multiplier`` (default 3 →
  "save 3× more often") for as long as the threat persists.
  Auto-locates via ipapi.co IP-geolocation when no
  latitude/longitude is supplied.  ``offline=True`` (or
  ``HYPERNIX_UPS_OFFLINE=1``) skips every HTTP call.

* **`hypernix.injection`** — token / phrase splicers for chat
  scaffolding tokens.  Four variants:
    * ``ThinkingInjector`` — wraps in ``<think>...</think>`` —
      the convention HyperNix-2 / Qwen-3 thinking mode /
      DeepSeek-R1 distilled checkpoints share.
    * ``TestingInjector`` — prepends ``<|test|>`` to short-
      circuit a chat oven into eval mode.
    * ``SystemOverrideInjector`` — appends a one-shot
      ``<|system_override|>...`` without disturbing the
      caller's persistent system prompt.
    * ``CustomInjector`` — generic open / close / mode triple.
  Two scopes: :meth:`inject_messages` for
  ``[{"role", "content"}, ...]`` lists, :meth:`inject_text`
  for already-rendered prompt strings.  Each injection is
  recorded in :attr:`history` for provenance.

* **`hypernix.plasma`** — quick GPU benchmark for sharper
  ETAs.  Runs a 6-step Llama-shape forward + loss + backward
  + AdamW.step loop sized to fit on a laptop GPU (and to
  finish in ~2 s on CPU), returning a :class:`PlasmaResult`
  with ``step_ms`` (median), ``tokens_per_sec``, and a
  ``calibration_factor``.  ``calibrate_alarm(alarm, result)``
  rebinds ``alarm.estimate_step_seconds`` so further calls
  scale by the measured factor — turns a generic
  ``GasAlarm(cpu_preset="i7-7700hq")`` ETA into one that
  reflects what the actual machine can do.  Autocast handled
  on CUDA so fp16 / bf16 configs don't explode on bf16-broken
  cross-entropy paths.

🖥️ **`tvtop` visual rewrite (the headline polish).**
The 0.60 dashboard worked but looked thin and got tripped by
non-training logs.  0.61.0b1 reworks the layout to btop++-style:

* **Multi-panel layout** — rounded-corner framed panels
  (``╭`` / ``╮`` / ``╰`` / ``╯``).  Side-by-side ``hardware``
  panel (CPU / RAM / GPU / VRAM bars + numbers) and
  ``training`` panel (step + progress bar, loss / lr / tput,
  elapsed / ETA).  Below: a full-width ``loss curve`` panel
  with a **5-row block-bar graph** (the new
  :func:`multi_row_graph` helper, quantised to ``height × 8``
  sub-pixels via the ``▁ ▂ ▃ ▄ ▅ ▆ ▇ █`` ladder), then a
  full-width ``recent log`` panel with the last 6 lines.
* **Auto-detect filter** — :func:`_looks_like_training_log`
  reads the first 16 KiB of each candidate log and keeps only
  the ones containing a ``step N/M loss=…`` match.  Ranks
  shaped logs above name-matched logs above arbitrary newest.
  Stops the dashboard from latching onto a Konsole / browser
  / system log.
* **Binary sanitisation** — ``_sanitise()`` replaces every
  byte in ``[0x00–0x08, 0x0B–0x1F, 0x7F–0x9F]`` with ``?``,
  so a binary-laced log can't render as ``�`` garbage.
* **Empty-state** — when no training data has been parsed
  yet, the training panel shows
  ``⏳ waiting for training data…`` instead of a fake
  ``step 0 / loss=—``.
* **Performance** — ``nvidia-smi`` cached for 3 seconds (was
  shelling out every 1-second refresh); cursor-home + per-line
  clear instead of full-screen erase per tick (less flicker);
  frame-diff suppression so the renderer skips writes when
  nothing visible changed.
* **ASCII fallback** — ``--ascii`` swaps every Unicode block
  char to ``# . : - = + *`` so non-UTF terminals stay readable.
* Rounded panel chars + colour gauges (green < 60% < yellow
  < 85% < red) make the panels actually pleasant to watch.

🛡️ **32 new tests** in ``tests/test_v061_b1.py`` covering
every UPS state transition (offline / panic-once-on-edge /
cadence triple / no-panic passthrough / history /
multiplier-floor), every Injection mode (text / messages /
prefix / suffix / wrap / factory / one-shot helper / history),
every Plasma path (returns shape / positive throughput /
summary string / alarm calibration / object-without-method
rejection / alias), and every tv polish bit
(``multi_row_graph`` shape / empty / constant / log
sanitisation / training-log autodetect filter / panel frames /
empty-state header).

Final: 800 tests pass, 1 skipped (matplotlib).

---

## 0.60.0

✨ **Eight new modules — four headline + four multi-tier.**

🖥️ **`hypernix.tv` + `tvtop` CLI** — btop++-style training
dashboard.  Tails any training log under cwd, parses
``step N/M loss=X lr=Y`` lines, and renders a live ANSI-colour
panel: progress bar with percent, loss sparkline (Unicode
block-bar by default; ``--ascii`` for non-UTF terminals),
throughput, elapsed wall time, ETA, CPU% / RAM% / GPU util%
/ VRAM (via ``nvidia-smi``), and the most recent log tail.
Zero hard dependencies — pure stdlib + ANSI.  Console script
``tvtop`` is registered in ``pyproject.toml``.

📦 **`hypernix.compactor`** — zip older checkpoints to save
disk.  ``Compactor(root, keep_recent=3, fmt="zip"|"tar"|"tar.gz")``
walks a snapshot directory, finds ``ckpt-NNNN`` /
``checkpoint-NNNN`` / ``step-NNNN`` directories (and matching
``.pt`` / ``.safetensors`` files), keeps the N most-recent
uncompressed, and rolls the rest into archives.  ``dry_run=True``
plans without touching the disk.

⚡ **`hypernix.ethanol` + `eth` CLI** — bounded GPU overclock.
``Ethanol(level=0..30)`` maps a single integer to bounded core /
memory / power-limit offsets (level 0 = full stock; level 30 =
``MAX_CORE_OFFSET_MHZ`` / ``MAX_MEM_OFFSET_MHZ`` /
``MAX_POWER_LIMIT_PCT``, all well below typical manual-OC
limits).  Refuses to apply without ``confirm=True`` or
``HYPERNIX_ETHANOL_CONFIRM=1``.  Vendor backends:
``nvidia-settings`` (full), ``nvidia-smi`` (power limit only),
``rocm-smi``, ``intel_gpu_frequency``.  Returned
``OverclockResult`` records what was attempted, what succeeded,
and any vendor-tool stderr.

🌑 **`hypernix.outage`** — turn the display off during training.
``with Outage(): train_for_six_hours()`` blanks the panel on
entry and **always** restores it on exit — clean finish,
KeyboardInterrupt, OOM, RuntimeError, doesn't matter.  Backends:
``xset dpms`` (X11), ``wlopm`` (Wayland), ``pmset`` (macOS),
``SendMessageW`` via ``ctypes`` (Windows).  Missing backends
log a note instead of raising.

🍳 **Four new 4-tier modules** (matching the established
multi-tier pattern of ``smoker`` / ``coffee_maker`` /
``espresso_maker`` / ``blender`` / ``toaster`` etc.):

* **`timer`** — countdown / interval / pomodoro helpers, all on
  a monotonic clock.
    * ``KitchenTimer``  — t1.  Plain countdown.
    * ``EggTimer``      — t2.  Countdown + ``on_ring`` callback
      fired exactly once when the timer crosses ``duration``.
    * ``IntervalTimer`` — t3.  Fires every ``interval_seconds``
      via ``should_fire()`` — ideal for throttling log emits /
      checkpoint saves / eval cadence inside a tight training
      loop.
    * ``PomodoroTimer`` — t4.  Alternates between
      ``work_seconds`` / ``rest_seconds`` blocks; ``state``
      returns ``"work" | "rest"``.

* **`thermometer`** — sample CPU / GPU temperatures.
    * ``InstantThermometer``  — t1.  One-shot read.
    * ``ProbeThermometer``    — t2.  Rolling window with
      ``recent_max / recent_mean / recent_min``.
    * ``InfraredThermometer`` — t3.  Per-source peak tracking +
      configurable warn / critical thresholds.
    * ``DigitalThermometer``  — t4.  Logs every reading to a
      JSONL file for post-mortem analysis.
  Sources: ``psutil.sensors_temperatures`` when installed,
  Linux ``/sys/class/thermal/thermal_zone*/temp`` fallback,
  ``nvidia-smi --query-gpu=temperature.gpu`` for the GPU.

* **`dishwasher`** — clean up training-run leftovers.
    * ``HandWash``   — t1.  Logs + ``__pycache__`` only.
    * ``QuickWash``  — t2.  HandWash + ``*.tmp`` / ``*.partial``
      / ``*.lock`` / ``.DS_Store``.
    * ``NormalWash`` — t3.  QuickWash + stale checkpoints
      (delegates discovery to :mod:`hypernix.compactor`).
    * ``HeavyDuty``  — t4.  NormalWash + intermediate fp16
      GGUFs + ``dist`` / ``build`` / ``.pytest_cache`` /
      ``.ruff_cache`` directories; opt-in
      ``purge_hf_cache=True`` also wipes
      ``~/.cache/huggingface``.
  Every tier supports ``dry_run=True`` and reports total bytes
  freed.

* **`strainer`** — drop low-quality dataset rows.
    * ``Colander``    — t1.  Empty / None / whitespace-only.
    * ``FineMesh``    — t2.  Colander + length floor / ceiling.
    * ``NutMilkBag``  — t3.  FineMesh + non-printable-character
      filter.
    * ``Cheesecloth`` — t4.  NutMilkBag + 8-gram Jaccard
      near-duplicate detection (``similarity_threshold=0.85``
      by default).
  Operates on dicts (``record["text"]``) or plain strings; the
  ``key`` arg points the strainer at a non-default field.

🛡️ **44 new tests** in ``tests/test_v060.py`` — checkpoint
discovery + zip / dry-run / unknown-fmt for ``compactor``,
level → offsets math + clamp + plan-without-confirm + CLI
help / invalid-level for ``ethanol``, backend detection +
context-manager round-trip + strict-mode for ``outage``,
sparkline / log-tail / step-loss-lr regex / progress clamp /
render / single-frame run for ``tv``, all four
timer / thermometer / dishwasher / strainer tiers + their
factories.

🔌 **Two new console scripts** registered in ``pyproject.toml``:
``tvtop`` → ``hypernix.tv:cli_main``, ``eth`` → 
``hypernix.ethanol:cli_main``.

---

## 0.52.6

🐛 **More forgiving `smoke_alarm` kwargs.**  Continuation of the
0.52.5 fix-up — same downstream ``chat_hypernix2.py`` script,
same Surface Pro, two more ``TypeError``s after the previous
patch landed::

    TypeError: GasAlarm.__init__() missing 1 required positional
    argument: 'time_budget_seconds'

    TypeError: Alarm.__init__() got an unexpected keyword argument
    'log_every'

The user's call shape is ``smoke_alarm.GasAlarm(cpu_preset="…",
log_every=10, save_every=100, ...)`` — an alarm being used as a
training-config holder.  Two further fixes:

* **`time_budget_seconds` now defaults to ``600.0``.** (Was a
  required positional arg.)  Picking a hardware preset is the
  more interesting signal; the time budget is a knob most
  callers default anyway.  ``RadsAlarm()`` / ``GasAlarm()`` /
  ``ModernAlarm()`` / ``AutoAlarm()`` all instantiate with no
  arguments now.
* **Base `Alarm` accepts `log_every` / `save_every` /
  `eval_every`.**  Training-loop cadence kwargs that real users
  type into config dicts.  RadsAlarm doesn't *use* them, but
  accepting them silently is friendlier than crashing.
  ``AutoAlarm`` also accepts and forwards them through
  ``_common_kwargs`` to the picked tier.

🛡️ **20 new regression tests** in ``tests/test_v052_6.py``:
both repro lines, default ``time_budget_seconds`` on every tier,
``log_every`` / ``save_every`` / ``eval_every`` accepted on every
tier, ``AutoAlarm`` forwarding the cadence knobs, and a realistic
``**cfg`` user-config-dict expansion test.

---

## 0.52.5

🐛 **`smoke_alarm` is forgiving about kwargs.**  Reported by a
downstream ``chat_hypernix2.py`` script running on an i7 7th-gen
Surface Pro:

    TypeError: GasAlarm.__init__() got an unexpected keyword
    argument 'cpu_preset'

…and after the script's own ``except`` fell through to
``RadsAlarm``:

    TypeError: Alarm.__init__() got an unexpected keyword
    argument 'max_steps'

Real users type the kwargs they intuitively expect.  ``cpu_preset``
is the *function name* for resolving CPU presets in
``hypernix.freezer``, so reaching for ``GasAlarm(cpu_preset=…)``
is the natural call.  Same for ``max_steps`` as a hard cap on
``recommended_steps()``.

Fix:

* **Base `Alarm` dataclass** gains three forgiving kwargs:
  ``max_steps: int | None``, ``cpu_preset: str | CPUPreset``,
  ``gpu_preset: str | GPUPreset``.  Every subclass
  (`RadsAlarm` / `GasAlarm` / `ModernAlarm`) inherits them, so
  none of them raise ``TypeError`` anymore on those kwargs.
* **`Alarm.recommended_steps()`** now caps the natural
  recommendation at ``self.max_steps`` when set (a CAP, not a
  target — recommendations below ``max_steps`` are unaffected).
* **`GasAlarm.__post_init__`** resolves a ``cpu_preset`` string
  into ``self.cpu`` via ``hypernix.freezer.cpu_preset``, and a
  ``gpu_preset`` string into ``self.gpu``.  An explicit
  ``cpu=`` / ``gpu=`` object takes precedence.  Pre-built
  ``CPUPreset`` / ``GPUPreset`` objects passed via the alias
  also work.
* **`AutoAlarm`** mirrors the same kwargs and forwards
  ``max_steps`` through ``_common_kwargs`` so the picked tier
  honours the cap.

🌶️ **Generational CPU aliases in `hypernix.freezer.cpu_preset`.**
``"i7_7th_gen"`` (the user's exact string) used to return
``None``.  Added a generation-family map so the natural-feeling
aliases resolve to a representative SKU:

* ``i7_7th_gen`` → ``i7-7700hq``
* ``i7-12th-gen`` → ``i7-12700h``
* ``i9-12th-gen`` → ``i9-12900k``
* ``i9-14th-gen`` → ``i9-14900k``
* ``ultra-7`` / ``core-ultra`` → ``core-ultra-7-155h``
* ``ultra-9`` → ``core-ultra-9-185h``
* …plus full coverage of i5 / i7 / i9 11th – 14th gen, Core
  Ultra Series 1 + 2.

Direct SKU lookups (``"i7-7700hq"``) still take the fast path —
the alias map is only consulted on a primary miss.

🛡️ **27 new regression tests** in ``tests/test_v052_5.py``
covering both lines from the user's repro, ``max_steps`` cap
semantics (no-op when natural rec is below the cap, ignores 0 /
None, hard-caps when smaller), explicit ``cpu_preset`` / 
``gpu_preset`` resolution, explicit-``cpu=`` precedence, every
generational alias, ``AutoAlarm`` forwarding, and kwarg
acceptance on every tier.

---

## 0.52.4

🐛 **`CodeOven.chat` no longer crashes with ``ValueError: too many
dimensions 'str'``.**  Reported on a downstream notebook running
the published wheel: a chat turn died deep inside
``torch.tensor([input_ids], dtype=torch.long, ...)`` because the
tokenizer's ``apply_chat_template`` returned a plain rendered
string instead of token IDs (some tokenizers ignore
``tokenize=True``).  ``list("hello world")`` produced
``['h', 'e', 'l', ...]``, and torch quite reasonably refused to
build a long tensor out of single-character strings.

The fix lives in two places:

* **New :meth:`CodeOven._coerce_token_ids` helper.**  Accepts
  every legal shape ``apply_chat_template`` is allowed to return
  and normalises into a flat ``list[int]``:

    * a plain ``str`` → re-encoded through ``self._encode``,
    * a 1-D / 2-D ``torch.Tensor`` → flattened then ``int(x)``-cast,
    * a ``BatchEncoding``-like object exposing ``.input_ids`` →
      recurses into the input-ids field,
    * ``list[int]`` / ``tuple[int, ...]`` → passthrough,
    * batched ``list[list[int]]`` → take the first batch,
    * ``list[str]`` (the buggy shape) → return ``None`` so the
      caller falls through to the cookbook / plain transcript
      path instead of crashing.

  The ``apply_chat_template`` call is also wrapped in a try /
  except so a tokenizer that simply raises is treated identically
  to a tokenizer that returns garbage — both fall through to the
  cookbook path.

* **Defensive guard in :meth:`CodeOven._run`.**  Coerces ``str``
  / ``torch.Tensor`` / generic-iterable inputs the same way as
  ``_coerce_token_ids`` and raises a clear ``TypeError("_run
  expected list[int] for input_ids; got …")`` if anything still
  slips through, instead of bubbling up the cryptic torch error.

🛡️ **19 new regression tests** in ``tests/test_v051_4.py``:

* The headline bug — chat does not raise ``too many dimensions
  'str'`` when the tokenizer's ``apply_chat_template`` returns a
  string.
* 1-D tensor return / 2-D batched tensor return /
  ``BatchEncoding``-like return / ``list[str]`` fallback.
* ``_coerce_token_ids`` unit coverage for str / list[int] /
  tuple[int] / 1-D Tensor / 2-D Tensor / empty Tensor / empty
  list / batched list / BatchEncoding-like / list[str] /
  unrecognised object.
* ``_run`` defensive guard accepts string and tensor inputs via
  coercion and raises ``TypeError`` with a useful message on a
  truly unrecoverable input.

---

## 0.52.3

🔧 Auto version bump from CI (no code changes vs 0.51.3).

---

## 0.51.3

✨ **`hypernix.quantize` rewrite — full llama.cpp catalog.**

The 6-type alias dict from 0.51.2 grew into a structured 30-entry
``QUANT_CATALOG`` of frozen ``QuantSpec`` dataclasses, one per
distinct llama-quantize target type, with bits-per-weight,
category, size factor (relative to fp16), human-readable notes,
and a ``recommended`` flag for the curated short-list.

* **Floats:** ``F32``, ``F16``, ``BF16``.
* **Legacy quants:** ``Q4_0``, ``Q4_1``, ``Q5_0``, ``Q5_1``,
  ``Q8_0``.
* **K-quants:** ``Q2_K``, ``Q2_K_S``, ``Q3_K_S``, ``Q3_K_M``,
  ``Q3_K_L``, ``Q4_K_S``, ``Q4_K_M``, ``Q5_K_S``, ``Q5_K_M``,
  ``Q6_K``.
* **IQ-quants (newer, importance-matrix friendly):** ``IQ1_S``,
  ``IQ1_M``, ``IQ2_XXS``, ``IQ2_XS``, ``IQ2_S``, ``IQ2_M``,
  ``IQ3_XXS``, ``IQ3_XS``, ``IQ3_S``, ``IQ3_M``, ``IQ4_NL``,
  ``IQ4_XS``.

49 aliases (incl. the original ``q4km`` / ``q5km`` shortcuts and
the dash-form ``q4-k-m``) all resolve through the catalog.  The
old ``QUANT_TYPES`` dict is preserved unchanged at the alias
layer — pre-0.51.3 callers keep working.

New helper API:

* ``quant_recommended()`` — curated short-list (F16, Q8_0,
  Q6_K, Q5_K_M, Q4_K_M).
* ``quant_by_category("float" | "legacy" | "k" | "iq")`` — every
  spec in a category, sorted ascending by bpw.
* ``quant_for_size(target_size_bytes, fp16_size_bytes)`` —
  picks the largest non-float spec that fits the byte budget;
  falls back to the smallest IQ tier if nothing fits.
* ``quant_estimate_size(quant_type, fp16_size_bytes)`` —
  pure-arithmetic size estimate (no llama-quantize required).
* ``quant_resolve_spec(alias)`` — alias → ``QuantSpec`` lookup
  with case-insensitive matching and dash/underscore normalisation.
* ``quant_list_types()`` — sorted list of every canonical name
  in the catalog.

``QuantSpec``, ``QUANT_CATALOG``, and all six helpers are
re-exported at the top level (``hypernix.QuantSpec``,
``hypernix.QUANT_CATALOG``, ``hypernix.quant_recommended``,
etc.).

🛡️ **37 new tests** in ``tests/test_v051_3.py`` covering:

* Catalog completeness (≥ 30 specs, every alias resolves, every
  spec has a positive bpw / known category / non-empty notes).
* ``QuantSpec`` is a frozen dataclass.
* ``recommended()`` short-list contents.
* ``by_category()`` sorted-by-bpw ordering and unknown-category
  empty return.
* ``for_size()`` happy path, tiny-target fallback, zero-fp16
  rejection.
* ``estimate_size()`` math against expected ranges.
* ``resolve_spec()`` canonical / short-alias / dash-alias /
  case-insensitive / unknown-raises paths.
* Backward-compat: every pre-0.51.3 alias still resolves,
  ``quantize_gguf`` still raises ``ValueError`` on unknown
  targets.
* Top-level re-exports present and identity-equal to the
  underlying objects.

📚 **README + wiki refreshed.**  README's quant-aliases table and
the ``hypernix.quantize`` row now describe the new catalog.
``wiki/Quantization.md`` opens with a v0.51.3 callout, the type
table covers every recommended bpw tier, and a new "Catalog
helpers" section shows ``quant_recommended`` /
``quant_by_category`` / ``quant_for_size`` /
``quant_estimate_size`` / ``quant_resolve_spec`` in action.
README also broadens the headline tagline to mention both the
chat-tuned ``ray0rf1re/hyper-Nix.2`` (current default) **and**
the original ``ray0rf1re/hyper-nix.1`` (still fully supported).

---

## 0.51.2.1

🐛 **PyPI logo broken-image fix (carried over from 0.51.1.2).**  The 0.51.1 / 0.51.1.1
README pointed at
``https://raw.githubusercontent.com/minerofthesoal/hypernix-pip/main/assets/logo.png``
but that path returns 404 — the logo file is on the
``claude/pytorch-quantization-package-cJMQp`` working branch
and hasn't been merged to ``main`` yet, so the PyPI project page
showed the alt text + a broken-image placeholder.  Fixed by
pinning the URL to commit ``2d5eb37`` (the upload commit), which
is permanent regardless of branch lifecycle.  PyPI renders the
logo from this release onward.  Once the branch lands on
``main`` we can switch back to the pretty
``main/assets/logo.png`` URL.

---

## 0.51.1.1

🎨 **Logo file landed.**  ``assets/logo.png`` (1408 × 768 RGBA,
670 KB) and the transparent-background variant
``assets/logo1.png`` are now in the repo, so the raw-GitHub
``<img>`` tag at the top of the README renders on the PyPI
project page from this release onward.  Originals also kept
under ``assets/logo/`` for archival.  No code changes vs
0.51.1.

---

## 0.51.1

🐛 **Five bug-fix patches across three review passes** — one
by-hand source-read pass and two hand-driven testing passes,
including a memory-leak / Pascal-GPU / CPU-leak audit.

* **`bell.Bell._iter_from_ids` — stop-marker leak.**  The
  stop-sequence check ran *after* yielding the offending token,
  so consumers wired up via ``iter_chat`` / ``iter_complete``
  saw ``"<|im_end|>"`` (or whatever the stop string was) appear
  in their stream before generation halted.  Fix: check the
  *candidate* decoded text BEFORE yielding the token.

* **`countertop.Countertop._trim` — wipes the just-added user
  turn.**  Aggressive trimming with a small ``max_history_tokens``
  could ``del self.history[:2]`` when ``len(history) == 2``,
  leaving an empty history right before the call to
  ``oven.chat(messages)``.  Fix: cap the drop count at
  ``len(self.history) - 1`` so the most-recent message always
  survives.

* **`cookbook._HYPER_NIX_2` — dict-aliasing footgun.**
  ``_HYPER_NIX_2`` was constructed with
  ``role_prefixes=_CHATML.role_prefixes`` (and same for
  ``role_suffixes``), so the two templates literally shared the
  same dict object.  Mutating ``COOKBOOK.get("chatml")``'s
  prefix table silently corrupted ``hyper-nix.2``.  Fix: copy
  the dicts at construction time.

* **`flour.Flour.process` — crashes on tensor input.**  The
  guard ``if produced_ids:`` raised
  ``RuntimeError: Boolean value of Tensor with more than one
  value is ambiguous`` when callers passed a ``torch.Tensor``.
  Fix: normalise ``produced_ids`` to a plain ``list[int]`` at
  the top of ``process`` and switch the gating to a length
  check; tensors, numpy arrays, and one-shot generators now all
  work.

* **`pressure_cooker.UniversalCooker.select` — breaks Pascal
  (sm_61) GPUs.**  The selector unconditionally returned
  ``ProCooker`` (which inherits ``InductionCooker`` with
  ``fused=True`` + CUDA graphs) on any CUDA device, but fused
  AdamW and ``torch.cuda.CUDAGraph`` both require compute
  capability ≥ 7.0.  A 1080 / 1080 Ti / Titan Xp user calling
  ``universal_cooker(model.parameters())`` would crash with
  ``RuntimeError: fused=True requires CUDA capability >= 7.0``.
  Fix: new ``_is_pre_volta(device)`` helper; the selector now
  detects Pascal and forces ``fused=False`` (with
  ``foreach=_HAS_FOREACH``) on a plain ``InductionCooker``.

🛡️ **14 new regression tests** in ``tests/test_v051_1.py`` —
one per behavioural requirement of the fixes (stop-marker
absence in stream / token-callback / done-callback; trim
preserves freshest user; cookbook dicts are independent and
non-aliasing; flour accepts torch tensors / generators / empty
inputs; ``_is_pre_volta`` returns False on CPU and the Pascal
selector path forces ``fused=False``).

🎨 **Project logo wired in.**  ``assets/logo.png`` is now
referenced from the top of the README (with a raw GitHub URL so
PyPI renders it on the project page) and is shipped in the sdist
via ``MANIFEST.in``.  ``DEFAULT_REPO_ID`` and the ``Homepage``
URL also updated to point at ``ray0rf1re/hyper-Nix.2``.

🔧 **Memory-leak audit (CPU + Pascal-GPU paths).**  Manually
exercised ``deep_fryer.LightFry`` (fry / un_fry over 50 iters,
``torch.Generator`` and ``torch.Tensor`` object counts both
delta-zero), ``Bell.iter_complete`` (20 streaming runs,
delta-zero), ``CodeOven.chat`` (10 turns, delta-zero).  No leaks
introduced by the v0.51.0 chat surface.

Final: 621 tests pass, 1 skipped (matplotlib).

---

## 0.51.0

✨ **Chat-first release.** Five new modules + first-class support
for the new ``ray0rf1re/hyper-Nix.2`` chat checkpoint.

* **`hypernix.cookbook` — chat-template registry.**
  Different model families use wildly different prompt formats
  (ChatML, Llama 3 turn tags, Alpaca, Vicuna, plain ``role:
  content``) and getting one wrong silently makes a chat model
  behave like a base model.  ``cookbook`` ships every common
  template as a dataclass and resolves the right one from a
  short name or HF repo id::

      from hypernix.cookbook import COOKBOOK, for_model

      tmpl = for_model("ray0rf1re/hyper-Nix.2")  # picks "hyper-nix.2"
      prompt = tmpl.apply(messages, add_generation_prompt=True)

  Built-in templates: ``chatml``, ``hyper-nix.2`` (ChatML +
  HyperNix-flavoured default system prompt), ``llama3``,
  ``llama2``, ``alpaca``, ``vicuna``, ``plain``.  Wired into
  ``CodeOven._format_chat`` as the layer-2 fallback (after
  ``tokenizer.apply_chat_template`` if present, before the plain
  ``role: content`` last-resort) so a freshly-downloaded
  hyper-Nix.2 snapshot Just Works for chat without any extra
  configuration.

* **`hypernix.countertop` — multi-turn chat session.**
  Persistent workspace bound to an oven::

      from hypernix.old_oven import preheat
      from hypernix.countertop import Countertop

      oven = preheat("hyper-nix.2")
      chat = Countertop(oven, system="You are a helpful chef.")
      print(chat.say("How do I dice an onion?"))
      print(chat.say("And a shallot?"))
      chat.save("session.json")

  Auto-resolves the chat template from ``oven.repo_id``,
  optionally streams through a :class:`Bell`, optionally cleans
  replies through a :class:`Flour`, trims oldest turns when the
  rendered transcript exceeds ``max_history_tokens``, and
  round-trips to JSON for resumable sessions.

* **`hypernix.menu` — system-prompt presets.**
  Named registry of personas: ``default`` / ``concise`` /
  ``code-helper`` / ``judge`` / ``creative`` / ``chef`` /
  ``hyper-nix``.  Pairs with the ``persona=`` kwarg on
  ``countertop()`` so you can say
  ``countertop(oven, persona="judge")`` instead of pasting the
  judge prompt by hand.  Persists with ``Menu.save / Menu.load``.

* **`hypernix.bell` — streaming-token callback.**
  Wraps any oven exposing ``model`` + ``_decode`` + ``_format_chat``
  so generation streams a token at a time::

      bell = Bell()
      bell.on_token(lambda tok, idx: print(tok, end="", flush=True))
      bell.on_done(lambda full: print(f"\\n[done, {len(full)} chars]"))
      bell.stream_chat(oven, messages, max_new_tokens=128)

  Or pull tokens out of the iterator yourself::

      for tok in bell.iter_chat(oven, messages):
          ...

  ``stdout_bell()`` and ``file_bell(path)`` are ready-made
  variants.  Bells accept a ``flour=`` so live logits processing
  applies during streaming, not just at the end.

* **`hypernix.flour` — chat-quality logits processor.**
  *The reason hypernix's chat surface is "better than raw
  transformers for chatting".*  Bundles every chat-quality
  heuristic you'd otherwise wire by hand on top of vanilla
  transformers:
    * **repetition penalty** (OpenAI-style multiplicative),
    * **frequency penalty** (linear in count),
    * **presence penalty** (linear, once per unique token),
    * **no-repeat n-gram** blocking,
    * **bad-word / phrase** suppression,
    * **role-leak suppression** — strips
      ``<|im_start|>user`` / ``[INST]`` / ``user:`` tokens the
      assistant would otherwise hallucinate, and cuts the reply
      at any half-emitted next-turn marker,
    * **stop-sequence detection** on **decoded text** rather than
      raw token ids — so ``"<|im_end|>"`` works even when the
      tokenizer splits it into 3 BPE pieces.
  ``Flour.smart_default(template="hyper-nix.2")`` applies all of
  the above with values tuned for chat.  ``Flour.aggressive()``
  cranks up the penalties for models that loop a lot.
  ``Flour.off()`` is a no-op.

🌶️ **First-class support for ``ray0rf1re/hyper-Nix.2``.**

* New ``KNOWN_MODELS`` entry plus the aliases ``hyper-nix.2`` /
  ``hyper-nix2`` / ``hypernix2`` / ``hyper-nix`` / ``hypernix``,
  all routing to ``ray0rf1re/hyper-Nix.2``.  The chat-aware
  ``hyper-nix`` / ``hypernix`` short names now resolve to v2
  (was v1 in 0.50).
* ``DEFAULT_REPO_ID`` updated to ``ray0rf1re/hyper-Nix.2`` so
  ``preheat()`` with no args downloads the chat-tuned model.
* New ``ARCH_PRESETS["hypernix2"]`` / ``["hyper-nix.2"]`` for
  fresh-init from-scratch chat models with the same Llama-shape
  config as v1.
* ``CodeOven.repo_id`` is now persisted on the oven so
  ``_format_chat`` can resolve the cookbook template
  automatically — no more ``role: content`` fallback for v2.

🛡️ **56 new tests** in ``tests/test_v051.py``: cookbook templates
(ChatML / Llama 2/3 / Alpaca / Vicuna / plain + ``for_model``
resolver), menu CRUD + persistence, bell streaming with a stub
oven (no real weights needed), countertop session lifecycle
(say / reset / trim / save / load / persona / flour-cleanup),
flour logits processor (repetition penalty math, no-repeat n-gram
ban, role-leak detection, decoded-text stop-match,
``clean_reply`` after generation), and hyper-Nix.2 wiring (alias
table, default repo id, oven ``repo_id`` plumbing).

Final: 607 tests pass, 1 skipped (matplotlib).

---

## 0.50.0

✨ **Four new kitchen modules.**

* **`hypernix.whisk` — checkpoint averaging.**
  Three modes for blending N saved snapshots into one set of
  weights, all working on plain ``dict[str, Tensor]``:
    * ``swa_average(items)`` — uniform Stochastic Weight Average
      (mean across all N).
    * ``ema(items, decay=0.99)`` — exponential moving average;
      later inputs weighted ``decay ** (N-1-i)``.
    * ``geometric_mean(items)`` — element-wise geometric mean
      (clamped at ``eps`` for non-positives).
  Inputs may be in-memory state dicts **or** paths to ``.pt`` /
  ``.safetensors``.  Mismatched keys are intersected with a
  warning unless ``strict=True``.  Integer tensors are taken from
  the first checkpoint (averaging them is meaningless).
  ``whisk(items, mode="swa"|"ema"|"geometric-mean")`` is the
  one-shot factory; ``whisk_to_snapshot(items, out_dir, ...)``
  whisks **and** writes a full HF-style snapshot directory in one
  call (best-effort config recovery from a sibling
  ``config.json``).

* **`hypernix.cutting_board` — train / val / test splitting.**
    * ``CuttingBoard(train_ratio, val_ratio, test_ratio,
      seed, shuffle)`` — deterministic random split.  Ratios are
      renormalised if they don't sum to 1.0; ``test_ratio=0`` is
      allowed (you'll get train + val and an empty test slice).
      ``.slice(source)`` returns ``{"train": [...], "val": [...],
      "test": [...]}`` from a corpus path or any iterable of
      strings; ``.slice_to_files(out_dir, suffix=".txt")`` writes
      each slice to its own file.
    * ``StratifiedBoard(label_key="label")`` — stratified split
      that preserves the class distribution from labelled records
      (each unique label is shuffled and split independently,
      then per-class slices are concatenated and shuffled once
      more so the output isn't grouped by class).
    * Convenience: ``cutting_board(source, train=…, val=…,
      test=…, seed=…)`` returns the slice dict directly when
      ``source`` is given, else returns a configured board.

* **`hypernix.apron` — RNG-state guard.**
  An apron protects what's underneath while you cook.  Captures
  every random-number source hypernix or your script might touch
  (Python ``random``, NumPy if installed, PyTorch CPU, every
  CUDA device's RNG) and restores it on exit.  Two ways to use
  it:

      with apron(seed=0):
          # everything inside is deterministic; nothing leaks out.
          random.shuffle(my_list)
          torch.randn(10)

      a = Apron.snapshot(seed=0)
      ...
      a.restore()

  Use it any time a step in your pipeline wants to perturb the
  global RNG (e.g. an evaluator that uses ``torch.randn`` for
  sampling) without leaking the perturbation back to the caller.

* **`hypernix.recipe_book` — named-config registry.**
  Save 12-key brew recipes once, refer to them by name forever.
  ``RecipeBook.add(name, recipe)`` / ``get(name)`` /
  ``remove(name)`` / ``save(path)`` / ``load(path)``.
  ``cook(name, **overrides)`` looks up, applies overrides on top,
  and dispatches by ``kind`` field:
    * ``"instant_pot"`` → ``hypernix.instant_pot.brew``
    * ``"cold_brew"`` → ``hypernix.coffee_maker.cold_brew(...).brew()``
    * ``"espresso"`` → ``hypernix.espresso_maker.espresso_maker(...).pull(prompts)``
  ``RecipeBook.from_builtins()`` ships a handful of ready-to-use
  recipes (``evaluator-quick``, ``ftune-pascal``,
  ``nightly-coldbrew``, ``espresso-eval``).

🐛 **Three bug-fix passes across the codebase.**

Pass 1 — runtime correctness:

* `pressure_cooker._adamw_multitensor`: the private
  ``torch.optim._functional.adamw`` API is **not** stable across
  torch 1.13 → 2.x.  Now wrapped in a try/except (both
  ``ImportError`` on the import and ``TypeError`` at call time),
  with a graceful fall-through to a hand-written
  ``_adamw_scalar_for(params, group)`` so the optimizer keeps
  working on torch versions where the private name was renamed
  or had its signature changed.
* `deep_fryer.LightFry` / `HeavyFry`: replaced the global
  ``torch.manual_seed`` mutation with a per-parameter
  ``torch.Generator(device=flat.device)`` keyed on
  ``self.seed + sum(map(ord, pname))``.  Two consecutive fries
  with the same seed now produce identical noise **without** also
  perturbing the user's training RNG state.
* `food_processor.SliceBlade`: previously accepted any
  ``overlap_chars`` and produced a zero-length step (infinite
  loop) when ``overlap_chars >= slice_chars``.  Now raises
  ``ValueError`` at chunk time with a clear message.
* `industrial_range._parse_pairwise`: the pairwise parser used
  to insist that "tie/tied/equal" be the first character of the
  judge response.  Real judges write things like "Tied — both
  responses are correct" or "Equal quality" — those now correctly
  return ``"T"``.

Pass 2 — UX / error-message clarity:

* `instant_pot.brew`: when ``recipe["dataset"]`` doesn't exist on
  disk, the old behaviour was a confusing ``KeyError`` deep inside
  ``train`` after a 30-second model download.  Now fast-fails with
  ``FileNotFoundError("instant_pot.brew: dataset … does not
  exist")`` before the download starts.
* `microwave._preheat`: a string repo id like ``"nix2.5"`` that
  happened to coincide with an existing local directory was being
  treated as a path even when the directory didn't contain a
  ``config.json``.  The path branch now also requires
  ``config.json`` before short-circuiting the Hub download.
* `cake_pan` `step_timeout` handler: the SIGALRM handler used to
  raise ``BakeOff`` directly without first restoring pristine
  state, leaving the model with a half-applied gradient step.
  Now calls ``self.roll_back()`` before raising.

Pass 3 — discovered during smoke-testing the new modules:

* `apron.Apron.snapshot`: the previous implementation seeded the
  RNGs **before** capturing state, so the ``with apron(seed=42):``
  context-manager exit restored to the seeded state instead of
  the caller's pre-call state.  Now snapshots first, then
  optionally seeds, so exit truly returns the caller to whatever
  they were doing before.

🛡️ **36 new tests** in ``tests/test_v050.py`` covering all four
new modules plus regressions for every bug fix above.

---

## 0.49.0

✨ **`hypernix.lunchbox` — consistent-schema dataset packager.**
Reported: the Hub dataset viewer on a hypernix-built
``ray0rf1re/eval`` dataset crashed with

  Error code: StreamingRowsError
  Exception:  CastError
  Message:    Couldn't cast … because column names don't match

The actual column layout (11 cols incl. ``latency_s``,
``keyword_score``, ``pipeline_meta``) didn't match the
``huggingface`` metadata blob embedded inside the Parquet shards
(only 4 cols).  That happens when shards written at different
schema versions get concatenated.  ``Lunchbox`` makes that
impossible by construction:

  * ``add(**fields)`` collects plain dicts.
  * ``normalize()`` fills every missing cell with ``None``.
  * ``validate()`` rejects mixed non-None types per column
    (str+float in the same column is a Parquet write error).
  * ``pack(path)`` routes through
    ``datasets.Dataset.from_list(...).to_parquet(...)`` so the
    embedded ``huggingface`` metadata is always in sync with the
    actual column set.
  * ``push_to_hub(repo_id)`` does the same for direct uploads.
  * ``Lunchbox.for_eval()`` pre-loads the recommended eval-dataset
    schema (``EVAL_SCHEMA``: id / category / difficulty / tier /
    prompt / reference / model_response / keyword_score /
    latency_s / variant / pipeline_meta).
  * ``pack_jsonl(path)`` writes the same normalised rows as JSON
    Lines — no pyarrow / datasets install required.

``datasets`` is a **lazy** dependency: the first pack / push call
routes through :func:`hypernix.deps.ensure`, respecting
``HYPERNIX_AUTO_INSTALL=0``.

🧪 **+31 new coverage tests** (`tests/test_coverage_beef.py`)
touching gaps in the existing per-module suites: lunchbox
edge cases (empty box, 10 000-row normalise, unicode,
duplicate rows, mixed-types rejection, push-URL shape),
pressure_cooker (amsgrad wiring, closure-form step, foreach
state persistence, repr text), deep_fryer (frozen-param
handling, multi-cycle save/restore, HeavyFry fries frozen
weights), cake_pan (CPU memory-guard no-op, oven-all-bad
zero count, step_count monotonicity), freezer presets (every
CPU has AVX, every GPU has positive bandwidth, lookup-key
normalisation), shakers (determinism, rate=0 identity, empty-
line passthrough), smoke_alarm (time_hours math, save_every=0
silence, unknown-preset error content), plus an end-to-end
evaluator→Lunchbox→JSONL→Table round trip.

Full suite 515 passed, 1 skipped (matplotlib).

---

## 0.48.0

✨ **`pressure_cooker` rewrite — 4 device-tuned tiers + universal
selector + 5 new knobs.**  The base :class:`PressureCooker` keeps
the v0.47 API exactly (warmup / plateau / cosine cooldown + optional
lookahead); on top of it ship four specialised classes and a
selector:

* **`StovetopCooker`** (CPU tier 1) — minimum-memory path:
  ``foreach=False``, ``fused=False``, no AMP.  Use on RAM-
  constrained boxes and old Intel Macs.
* **`ElectricCooker`** (CPU tier 2) — ``foreach=True`` multi-tensor
  path (torch ≥ 1.12) for fast CPU updates when you have the RAM.
* **`InductionCooker`** (GPU tier 1) — ``foreach=True`` +
  ``fused=True`` AdamW kernel on torch ≥ 2.0 + first-class
  ``torch.cuda.amp.GradScaler`` integration.  Pass
  ``grad_scaler=torch.cuda.amp.GradScaler()`` and the cooker
  unscales, inf-skips, and advances the scaler automatically.
* **`ProCooker`** (GPU tier 2) — InductionCooker plus optional
  CUDA-graph capture via ``warmup_graph(step_fn)`` /
  ``replay_graph()`` for a material speedup on fixed-shape steps.

✨ **`universal_cooker(params, prefer_speed=True)`** — probes the
first parameter's device and returns `ElectricCooker` on CPU (or
`StovetopCooker` with `prefer_speed=False`), `ProCooker` on CUDA
(or `InductionCooker`).

✨ **New base-class knobs (opt-in, all backward-compatible):**

* ``grad_scaler=`` — unscales, skips on inf, advances the scaler.
* ``grad_accum_steps=N`` — only the N-th ``step()`` runs the
  optimizer; earlier calls just bump the counter.
* ``foreach=True | False | None`` — selects the multi-tensor path.
* ``fused=True | False | None`` — selects the fused CUDA kernel
  when torch supports it (torch ≥ 2.0, all params on the same
  CUDA device).
* ``amsgrad=`` — forwarded to the inner AdamW.

✨ **Factory convenience:** ``pressure_cooker(params, tier="...")``
accepts any of ``"pressure-cooker"`` / ``"stovetop"`` / ``"electric"``
/ ``"induction"`` / ``"pro"``.  Unknown tiers raise
``ValueError`` with the full list.

🔧 `describe()` method on the base class returns a dict of the
active knobs for logging / provenance.

Tests (`tests/test_pressure_cooker_v048.py`, 19 new):

* v0.47 signature + LR schedule + phase labels unchanged (backward
  compat).
* Every tier's defaults (`foreach`, `fused`, `grad_scaler`) verified.
* Universal selector picks Electric on CPU (fast) or Stovetop
  (safe).
* Grad-accumulation: N-1 no-op steps then one real update.
* GradScaler: skip-on-inf path *and* update-on-finite path via a
  fake scaler so we don't need CUDA to test.
* Scalar vs. foreach inner path produce the same weight update to
  within fp rounding.
* Factory tier lookup + error paths.
* Lookahead slow-weight population survives the rewrite.

Full suite 469 passed, 1 skipped (matplotlib).

Docs: README subsystem table row rewritten to list all five tiers,
wiki/Home.md version history picks up 0.48.0 + backfills 0.47.1.

---

## 0.47.0

✨ **`deep_fryer`** — 2-tier model-weight perturbation.  `LightFry`
(t1): 2% of elements, 0.1× param-std Gaussian noise — use as a
regulariser between epochs.  `HeavyFry` (t2): 30% of elements,
0.5× noise, plus configurable zero-rate for sparse destruction —
use to generate deliberately-bad-model negatives for training a
judge, or for robustness testing.  Both are in-place and reversible
via `save_pristine()` / `un_fry()`.

✨ **`cake_pan`** — hybrid CPU + GPU training guard.  Wraps each
step in `bake(fn)` which catches NaN / Inf in the loss (and
optionally gradients), enforces a wall-time watchdog via SIGALRM,
monitors GPU memory and offloads matching modules when pressure
passes `free_gb_trip`, and rolls back to the last pristine state
on trouble — raising `BakeOff(reason, step)` for the caller.
`CakePan.oven(batches, step_fn)` is the fire-and-forget loop
wrapper with automatic retry + skip.

✨ **CPU preset expansion — now 48 total** (was 16, **×3**).
Adds 7th-gen i5 (7200U, 7300HQ, 7400, 7600K), i9 (7900X, 7980XE);
11th-gen i5 (11400, 11600K, 11320H), i9 (11900K); 12th-gen i5
(12400, 12500, 12600K), i9 (12900K, 12900HX); 13th-gen i5 (13400,
13500, 13600K), i9 (13900K, 13900HX); 14th-gen i5 (14400, 14500,
14600K), i9 (14900K, 14900KS, 14900HX); Core Ultra 5 Series 1
(125H, 135H, 228V), Series 2 (225K, 235K); Core Ultra 9 Series 1
(185H).

✨ **GPU preset expansion — now 71 total** (was 20, **×3.5**).
Adds the rest of GTX 10 (1050, 1050 Ti, 1060, 1070, 1070 Ti), GTX
16 (1650, 1650 Super, 1660, 1660 Super), RTX 20 (2060, 2060 Super,
2070, 2070 Super), full RTX 30 (3050, 3060, 3060 Ti, 3070, 3070
Ti, 3080, 3090, 3090 Ti), full RTX 40 (4060, 4060 Ti 8/16GB, 4070,
4070 Ti, 4080, 4090), full Blackwell consumer RTX 50 (5070, 5070
Ti, 5080, 5090).  **Apple Silicon** via MPS: M1 / M1 Pro / M1 Max
/ M1 Ultra, M2 / M2 Pro / M2 Max, M3 / M3 Pro / M3 Max, M4 / M4
Pro / M4 Max.  **AMD**: Radeon RX 6800 XT / 6900 XT / 7900 XT /
7900 XTX, Instinct MI250X / MI300X.  Non-CUDA devices (Apple,
AMD) use the `(0, 0)` sentinel for `compute_capability`.

Tests (`tests/test_v047_deep_fryer_cake_pan_presets.py`, 76 tests):
every fryer tier + pattern filter + unknown-tier error; cake_pan
loss/grad NaN detection, snapshot writes, oven retry counting,
pristine rollback; every new CPU preset spec + preset count bound;
every new GPU preset vram + count bound; compute-capability
sentinels for Apple + AMD.  **Full suite 447 passed**, 1 skipped
(matplotlib).

---

## 0.46.1

🛡️ **`nix` short-name fallback chain.**
`KNOWN_MODELS["nix"]` now points at `Nix-ai/Nix-2.7a` (was
`ray0rf1re/Nix2.5`).  `download_model("nix")` consults a new
`FALLBACK_CHAINS` registry and tries in order:
`Nix-ai/Nix-2.7a` → `Nix-ai/Nix2.6-mm` → `ray0rf1re/Nix2.5`,
falling through only when an earlier candidate 404s / is gated /
hits a network error.  Explicit `org/repo` ids bypass the chain.
Six regression tests in `tests/test_nix_fallback.py` cover the
happy path, fallthrough, exhaustion, and explicit-repo bypass.

---

## 0.46.0

✨ **`salt_shaker`** — 3-tier gentle data augmentation.

- `FromTheBag` (t1): per-character substitution at `rate`, preserves
  line length.
- `HandCrusher` (t2): adjacent-token swaps at `rate`.
- `PoshSaltDish` (t3): independent drop / duplicate / swap rates
  with word-level granularity.

All three share a `Shaker` base, a deterministic `seed`, and plug
into `sink.Sink.pour(...)` like the pans.

✨ **`pepper_shaker`** — 3-tier sharp perturbations.

- `SmallShaker` (t1): random token masking with configurable
  `mask_token` (default `[MASK]`).
- `Dish` (t2): typo injection (drop / duplicate an internal char);
  preserves first + last character so words stay recognisable.
- `TallHandmade` (t3): negation injection; prepends `negator`
  (default `"NOT"`) at `rate`.

✨ **`torch_compat`** — portability shim for **old Intel Macs with
torch 1.13**.  Provides version-gated fallbacks for
`torch.nn.RMSNorm` (needs ≥ 2.4) and
`torch.nn.functional.scaled_dot_product_attention` (needs ≥ 2.0).
`HyperNixModel` + `NanoNanoModel` now route through the shim, so
identical outputs on modern and legacy torch.

✨ **`[legacy-torch]` extra** — companion dep pins that co-install
with torch 1.13: `numpy<2`, `safetensors>=0.3.1`,
`huggingface-hub>=0.16`, `tqdm>=4.64`, `sentencepiece>=0.1.99`.
Does **not** relax the main torch pin; you must install torch 1.13
first yourself.  See `scripts/install_macos_legacy.sh`.

🔧 **`scripts/install_macos_legacy.sh`** — one-shot installer that
pins torch 1.13.1 CPU, installs hypernix with `--no-deps`, then
pulls the legacy-torch extras, and smoke-tests
`torch_compat.describe()`.

📚 New `wiki/macOS-legacy.md` documents what works, what doesn't,
and how to size training on old Intel Macs (`OldFreezer` + a
`GasAlarm(preset="i7-7660u")`-style budget).

---

## 0.45.3

🛡️ **`smoke_alarm.GasAlarm` accepts `preset=`.** One-string shortcut
that resolves against `GPU_PRESETS` first, then `CPU_PRESETS`. Works
on the class (`GasAlarm(..., preset="i7-7700hq")`), on the factory
(`gas_alarm(..., preset="h100")`), and on the selector
(`auto_alarm(..., preset="rtx-3080-ti")`). Unknown names raise
`ValueError` with the full list of valid presets.

🛡️ Explicit `cpu=` / `gpu=` instances still win over a conflicting
`preset=` hint — no silent overwrite.

🔧 Shared `_resolve_preset` helper in `smoke_alarm.py`.

## 0.45.2

🐛 **Every pan accepts `context_length=` and `max_chars=`.** Reported:
`FryingPan(context_length=CONTEXT_LEN)` raised a bare `TypeError`.
Both are now keyword-only fields on the `Pan` base class; when set,
lines are truncated to fit. `context_length` is treated as
`max_chars = context_length * 4` (English-BPE heuristic); the direct
`max_chars=` wins when both are set. For precise chunking by tokens
use `hypernix.food_processor` instead.

## 0.45.1

🐛 **Pan positional-argument fix.** `Pan` inherited `name: str` as a
dataclass field, so `Skillet(src, "instruct")` silently set
`name="instruct"` and left `mode="chat"`. Fix: `name` is now a
`typing.ClassVar` on every pan — still the pan's label, no longer
part of `__init__`. `GrillPan._seen` (internal dedupe state) marked
`init=False`.

🛡️ `pick_pan` error messages now list valid tiers / valid kwargs
instead of raising `KeyError` or cryptic `TypeError`.

## 0.45.0

✨ **Espresso, blender, toaster, food_processor, smoker** — five new
appliances, each 4 tiers. Shared interface per module.

✨ **+3 microwave tiers** — now `defrost` (preheat-only) / `low_zap`
(deterministic one-liner) / `zap` (existing) / `high_zap`
(long-temp draft) / `chat_zap` (existing). Plus `reheat(oven,
prior_output)` for continuation without rebuild.

✨ **+2 coffee_maker tiers and one new type.**
`FrenchPressMaker` (batch), `PercolatorMaker` (cyclic with optional
convergence), and a new `ColdBrewMaker` (long single brew with
mandatory JSON checkpoints, resumes cleanly after a crash).

✨ **CLI `hypernix brew recipe.json`** — runs `instant_pot.brew`
from a JSON recipe. Supports `--set KEY=VALUE` overrides with JSON
literals.

📚 `wiki/Kitchen.md` gets full sections for every new appliance.

## 0.44.0

✨ **Kitchen modules + pressure_cooker optimizer.** Seven new
top-level modules (pans, microwave, table, sink, instant_pot,
coffee_maker, pressure_cooker) covering preprocessing, throwaway
inference, log inspection, file output, end-to-end pipelines,
scheduled repetition, and a custom optimizer.

✨ `pressure_cooker` — `torch.optim.Optimizer` subclass: AdamW +
three-phase LR schedule (linear warmup → plateau → cosine cooldown)
+ Zhang-et-al-2019 Lookahead "pressure seal". No separate scheduler
object; the LR lives inside the optimizer.

📚 README gains a **"Who this is actually for"** section framing the
package around the solo-GPU / consumer-card / QLoRA-to-Hub workflow,
with an explicit disclaimer that `train()` is a smoke-tester, not a
production trainer. New `wiki/Kitchen.md`.

## 0.43.0

✨ **`smoke_alarm`** — four-tier training-step planner + mid-run
monitor. `RadsAlarm` (constants, lightest), `GasAlarm` (CPU/GPU
presets), `ModernAlarm` (warmup-measured), `AutoAlarm` (selector).

✨ **16 CPU presets** (`hypernix.freezer.CPU_PRESETS`): i7 7th gen
(7660U / 7700HQ / 7700K), 11th–14th gen K/H/HX, Core Ultra Series 1
(Meteor / Lunar Lake), Series 2 (Arrow Lake, AVX10).

✨ **20 GPU presets** (`hypernix.freezer.GPU_PRESETS`): Hopper
(H100/H200), Ampere workstation (A4500–A6000), RTX PRO Ada +
Blackwell, RTX 4070 Ti Super / 4080 Super, RTX 3080 Ti, Turing
consumer (1660 Ti, 2080, 2080 Super, 2080 Ti), Pascal (1080, 1080 Ti).

📚 New `wiki/Alarms.md` with both preset tables.

## 0.42.0

✨ **`new_range` / `old_range` / `industrial_range`** — three
sophistication tiers of labeling rubrics that drop into
`mediocre_fridge.collect_responses_from(label_rule=...)`.

- `new_range` — zero-dep first-fail rubric (is_empty, is_refusal,
  math_lacks_digit, is_repetition).
- `old_range` — weighted-mean scored rubric with `None` = "no
  opinion", any-rule-at-0 short-circuits to BAD, references / keywords
  / stopword-filtered overlap built in.
- `industrial_range` — LLM-as-judge wrapper around any CodeOven;
  pointwise + pairwise with caching.

📚 New `wiki/Ranges.md`.

## 0.41.0

✨ **CUDA 6.1 / Pascal support.** `compute_capability`, `is_pascal`,
`pascal_safe_dtype` (fp32 on CPU, fp16 on Pascal / Volta / Turing,
bf16 on Ampere+), `pascal_mode_hints` (one-stop dict of recommended
settings for sm_61).

✨ **`examples/train_hypernix_1_5_gtx1080.py`** — HyperNix 1.5,
verified 92,130,048 params, trains on an 8 GB Pascal card via
`auto_freezer` + `flash_freezer(slow=True)`.

📚 New `wiki/Pascal.md` with a full sm_61 playbook.

## 0.40.0

✨ **`freezer` module** — VRAM manager. `OldFreezer` (8 – 10 GB,
batch=1, fp16, empty_cache each step), `NewFreezer` (11 GB+, batch=8,
fp32/bf16), `FlashFreezer` (OOM-safe retry wrapper with exponential
backoff, wait-for-free-GB, and optional slow-mode that halves
`current_batch_size` on each retry).

📚 New `wiki/Freezer.md`.

## 0.36.0

✨ **`old_fridge` / `mediocre_fridge` / `new_fridge`** — memory
housekeeping (freeze/unfreeze/parameter_stats), judge-training dataset
synthesis, and training-curve plotting.

✨ `examples/train_hypernix_0_1_5_evaluator.py` — end-to-end example
wiring ovens + all three fridges.

📚 New `wiki/Fridges.md`.

## 0.35.0

✨ **Gemma 4, Qwen 3.5 & 3.6, GLM 5.x, Nix collection presets.** New
entries in both `ARCH_PRESETS` (for `new_oven`) and `KNOWN_MODELS`
(for short-name resolution). Config knobs verified against the actual
HuggingFace repos.

## 0.34.0

✨ **AutoModel fallback.** `load_snapshot` routes any non-HyperNix
`model_type` (Gemma, Phi, DeepSeek, GLM, GPT-OSS, …) through a thin
`transformers.AutoModelForCausalLM` wrapper. New ARCH_PRESETS covering
those families.

## 0.33.0

✨ **Windows + macOS support.** Cross-platform `doctor`, path
handling, `llama-quantize` resolution.

✨ **Python 3.13** support (sentencepiece 0.2.1 floor).

✨ **Runtime auto-install.** `HYPERNIX_AUTO_INSTALL` env var (default
on) lets missing runtime deps be installed lazily; `hypernix doctor
--fix` makes it explicit.

## 0.32.1

🐛 Fall back to the slow tokenizer when the `tokenizers` crate is too
old to decode a newer tokenizer.json.

## 0.32.0

✨ **torch 2.7+** (incl. CUDA 11.8 builds).

✨ One-shot PyPI publish via GitHub Actions Trusted Publishing.

## 0.31.0

✨ **Chat REPL.** `hypernix chat --repo-id <short-name>` plus
`CodeOven.chat(turns, ...)`.

✨ **Nano-nano / Nano-mini / nano-nano-927** family — new entries in
`KNOWN_MODELS`.

## 0.30.0

✨ **`old_oven` code-generation wrapper.** `preheat`, `CodeOven`,
`bake_code`, `fill_middle`, `save_pt` / `load_pt`. `--auto-oven`
top-level CLI shortcut.

## 0.21.0

✨ Download every file the model needs — not just weights — so the
output directory is a self-contained snapshot.

## 0.2.0

✨ First subcommand-based CLI. `train` module scaffold. Fixed
`tokenizer.ggml.merges` in GGUF output.

---

## Upgrading

`hypernix` follows no breaking-change policy yet. Patch releases
(`0.45.x`) are always safe to upgrade — they only fix bugs, UX
papercuts, or improve error messages.

Minor releases (`0.N.0`) add features. The usual gotcha is renamed
kwargs from the UX-polish patches above; when in doubt, check the
signature:

```python
import inspect
from hypernix import smoke_alarm, pans

print(inspect.signature(smoke_alarm.GasAlarm))
print(inspect.signature(pans.FryingPan))
```

## Contributing changelog entries

New features should land with a one-paragraph entry at the top of
this file, grouped by emoji legend. Patch releases get a couple of
bullet points; minor releases get a section per subsystem touched.
Keep the tone utilitarian — what changed, how the caller notices,
what to do instead if an old call stopped working.

---

## 0.61.4

🖥️ **Interactive TUI/CLI (`hypernix-cli`)** — Rich-based interactive menu system with fallback mode for all major operations: model management, training control, ASR/TTS pipelines, AI assistant, and Web UI launcher. Commands include `models`, `train`, `asr`, `tts`, `pipeline`, `assistant`, and `webui`.

🤖 **Linux Local AI Assistant** — Voice-controlled AI assistant with ASR input, natural language TTS responses, and system control capabilities. Built-in commands: `/help`, `/voice`, `/system`, `/quit`. Features persistent memory and conversation context.

🌐 **Web UI with Tailscale Integration** — Modern web dashboard at `http://localhost:8080` with secure Tailscale tunneling for remote access. Provides model management, training monitoring, ASR/TTS pipeline controls, and chat interface.

🔊 **Enhanced ASR/TTS Pipelines** — Improved `ASRToTTS` direct speech-to-speech conversion and enhanced `ASRToLLMToTTS` full conversational pipeline with better error handling, device management, and streaming support.

📦 **30+ New Model Architectures** — Added support for:
- LiquidAI LFM2.5-8B-A1B (GGUF quantized)
- OpenBMB MiniCPM5-1B
- Google Gemma 4 family (all variants including 31B-it, 12B, 4B, 1B)
- Qwen3.5 series, Phi-4, DeepSeek-V2.5, GLM-Edge/MoE
- GPT-OSS, Nemotron, Llama-3.2, Mistral-Nemo, Mixtral-8x22B
- Full Nano-Nano collection (ray0rf1re/nano-nano)
- And 15+ additional architectures for vision, audio, and language tasks

🛡️ **Pressure Cooker V2 Improvements** — Fixed lookahead slow buffer initialization bug that silently disabled lookahead optimization. Added comprehensive test coverage for both scalar and multitensor paths with Q8/Q6/Q5.5/Q4M quantization-aware training.

📚 **Documentation Updates** — Complete changelog preserved, README updated with new features, wiki expanded with usage examples for all new modules.

🔧 **Dependency Updates** — Updated requirements for latest transformers, accelerate, bitsandbytes, and TTS/ASR libraries. Added tailscale-python for secure tunneling.

---

## Contributing changelog entries
