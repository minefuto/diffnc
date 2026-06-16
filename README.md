# diffnc(DIFF for Network device Configurations)

![PyPI - Python Version](https://img.shields.io/pypi/pyversions/diffnc)
![PyPI - Version](https://img.shields.io/pypi/v/diffnc)
![GitHub License](https://img.shields.io/github/license/minefuto/diffnc)

A Python library and CLI that diffs network device configurations **with structural awareness**, exposed through a `difflib`-like API.

* Duplicate same-name blocks (e.g. `interface eth1` appearing more than once) are merged at parse time
* **Only sections where order carries meaning emit order diffs** (Junos `firewall filter` / `policy-statement` terms, Cisco `access-list` / `policy-map`, etc.). Everywhere else, reordering alone produces no diff
* Vendor is auto-detected. Diffing across vendors raises an error
* Supported vendors: **Cisco NX-OS**, **Cisco IOS**, **Cisco IOS-XE**, **Cisco IOS-XR**, **Arista EOS**, **Junos** (hierarchical), **Junos set** (`display set` format)

## Installation

```bash
pip install diffnc
```

For development:

```bash
uv sync
```

## Library usage

```python
from diffnc import unified_diff, ndiff

with open("router-before.conf") as f:
    a = f.read()
with open("router-after.conf") as f:
    b = f.read()

# Structural unified diff (shows changed lines and their parent sections only)
for line in unified_diff(a, b, fromfile="before", tofile="after"):
    print(line, end="")

# Full ndiff
for line in ndiff(a, b):
    print(line, end="")
```

To force a specific vendor:

```python
unified_diff(a, b, vendor="junos_set")
```

To only run detection:

```python
from diffnc import detect_vendor
detect_vendor(open("config.conf").read())  # -> "nxos"
```

### `reconcile` (experimental)

> **Experimental.** The output shape and exact command sequences may change in future releases. Always review the generated commands before applying them to a live device.

`reconcile(a, b)` returns the bare config-mode command lines that, when entered on a device currently running config *A*, bring it to the state described by config *B*.

```python
from diffnc import reconcile

for line in reconcile(a, b):
    print(line)
```

Output is config-mode commands only — no `configure terminal` / `end` / `commit` wrappers. Lines are indented to mirror the section hierarchy (using each vendor's own indent unit), so the result reads like the source config; flat vendors such as Junos set form emit no indentation. Pipe through your own session manager.

* **Cisco-like (NX-OS / IOS / IOS-XE / IOS-XR / EOS):** emits section navigation plus `<line>` for adds and `no <line>` for deletes. `X` / `no X` toggles are tracked as state: a transition (e.g. `no shutdown` → `shutdown`) emits just the new value, while a *removed* toggle resets to default — `default <cmd>` on vendors that support it (IOS / IOS-XE / NX-OS / EOS) and the inverted `no` on IOS-XR.
* **Junos hierarchical:** emits flat `set <path>` and `delete <path>` lines.
* **Junos set:** emits `<line>` verbatim for adds and `delete <path>` (with the `set ` prefix stripped) for deletes. `activate` / `deactivate` are tracked as state: a removed toggle inverts to its counterpart (`deactivate X` → `activate X`) rather than deleting the underlying `set`.
* **Order-sensitive sections** (ACL, `policy-map`, Junos `firewall filter` / `policy-statement` terms): on any change, the entire section is deleted and recreated from *B* — partial in-place edits are not attempted.

Exceptions:

| Exception | When it is raised |
| --- | --- |
| `VendorMismatchError` | The two configs are detected as different vendors (e.g. Junos set vs. Junos hierarchical is also rejected here) |
| `ParseError`          | Vendor detection failed, syntax error, etc. |

## CLI

```
diffnc [OPTIONS] FILE_A FILE_B

  -u, --unified           Structural unified diff (default)
  -n, --ndiff             Full ndiff output
  -r, --reconcile         Emit config-mode commands that transform FILE_A into FILE_B (experimental)
  --vendor {junos,junos_set,nxos,ios,iosxe,iosxr,eos}
                          Skip auto-detection and use the given vendor
  --color {auto,always,never}
                          Colorize +/- lines (auto = tty detection)
  --version
```

Exit codes follow `diff(1)`: `0` = no differences, `1` = differences found, `2` = error.

Example:

```bash
$ diffnc before.conf after.conf
--- before.conf
+++ after.conf
+feature ospf
 interface Ethernet1/1
-  description uplink
+  description uplink-to-spine
```

Or, in reconcile mode (**experimental**):

```bash
$ diffnc before.conf after.conf -r
interface Ethernet1/1
  description uplink-to-spine
feature ospf
```

## Example: normalizing duplicate blocks

Input A:

```
interface eth1
  no shut
  ip address 1.1.1.1/24
  stp
```

Input B (the same `interface eth1` appears twice):

```
interface eth1
  shut
  ip address 1.1.1.1/24

interface eth1
  stp
```

`ndiff` output:

```
  interface eth1
-   no shut
+   shut
    ip address 1.1.1.1/24
    stp
```

## How order is handled

Network device configurations mix "sections whose semantics don't depend on order" with "sections where order determines behavior." diffnc diffs **order-insensitively by default** and only does **position-based comparison for parent paths where order carries meaning**.

### Order-insensitive (reorder ≠ diff)

Most containers fall into this bucket. Examples: `system`, `interfaces`, `routing-options`, `vrf context`, top-level `interface ...`, `route-map FOO permit <seq>`, and so on. Reshuffling the children alone produces an empty diff.

```
# A
system {
    host-name foo;
    domain-name example.com;
}

# B
system {
    domain-name example.com;
    host-name foo;
}

$ diffnc a.conf b.conf   # → no diff, exit 0
```

### Order-sensitive (reorder = diff)

The paths below are evaluated in declaration order by the device, so swapping term/ACE/class order produces diff output.

| Vendor | Parent path | Children |
| --- | --- | --- |
| Junos | `firewall.filter <name>` | `term <name>` |
| Junos | `firewall.family <fam>.filter <name>` | `term <name>` |
| Junos | `policy-options.policy-statement <name>` | `term <name>` |
| Cisco-like (IOS / IOS-XE / IOS-XR / NX-OS / EOS) | `ip access-list <name>`, `ipv6 access-list <name>`, `mac access-list <name>` | ACE lines |
| Cisco-like (same as above) | `policy-map <name>` | `class <name>` blocks |

Pure reorders (children whose rendered subtree is byte-identical on both sides, just in a different position) are surfaced with a `!` marker, once per moved subtree. Children whose contents also changed continue to use `-` / `+` pairs.

Example: swapping two byte-identical terms inside a Junos firewall filter

```diff
 firewall {
     filter F {
!        term B {
!            then discard;
!        }
     }
 }
```

Example: a reorder of one term plus a content change in another term

```diff
 firewall {
     filter F {
!        term A {
!            then accept;
!        }
         term B {
-            then discard;
+            then reject;
         }
     }
 }
```

### Customizing the behavior for a new vendor

The `VendorParser` protocol exposes `is_order_sensitive(path: tuple[str, ...]) -> bool`. `path` is the tuple of `line` values from the root down to "the parent node whose children are being compared." Returning `True` makes the children compared positionally via `SequenceMatcher`; returning `False` (the default) falls back to set-style key comparison. If you're subclassing the Cisco family, the shortest path is to pass `order_sensitive_predicate` to `CiscoLikeParser(...)`.

## Development

```bash
uv sync
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run ty check        # type check
```

## Adding a new vendor

Create a new module under `src/diffnc/vendors/`, expose an implementation of the `VendorParser` protocol (`src/diffnc/vendors/base.py`) as `PARSER`, call `register(_yourvendor.PARSER)` from `src/diffnc/vendors/__init__.py`, and add the corresponding case to the detection logic in `src/diffnc/detect.py`.

`VendorParser` requires the following methods:

* `parse(text) -> ConfigTree`
* `format(tree) -> list[str]`
* `render_open(node, depth) -> str`
* `render_close(node, depth) -> str | None`
* `render_leaf(node, depth) -> str`
* `is_order_sensitive(path) -> bool` (optional; treated as always `False` if not implemented. See the "How order is handled" section.)
* `render_reconcile(events) -> Iterator[str]` (optional; required only to support `reconcile`. Receives a sequence of `ReconcileAdd` / `ReconcileDelete` / `ReconcileRecreate` events from `diffnc.reconcile` and yields the corresponding CLI lines.)
* `toggle_partners(a, b) -> bool` / `is_toggle_state(line) -> bool` (optional; both default to `False`. Let `reconcile` recognise paired toggle states — e.g. `X` ↔ `no X`, `activate` ↔ `deactivate` — so a transition emits only the new value and a removed toggle is excluded from value-change matching.)

## License

MIT
