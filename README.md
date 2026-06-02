# poplink

Open paths from your current tmux pane without touching the mouse.

`poplink` captures pane text, extracts local file paths and file locations, lets
you choose one with `fzf`, then opens it in your editor.

## Install

For local development:

```sh
git clone <repo-url> ~/poplink
export PATH="$HOME/poplink/bin:$PATH"
```

## Tmux Binding

```tmux
bind-key o display-popup -x C -y C -w 92% -h 85% -T " poplink " -d "#{pane_current_path}" -E 'poplink --hold-on-error'
```

## Usage

```sh
poplink
poplink --lines 300
poplink --history
poplink --visible
poplink --include-dirs
poplink --hold-on-error
poplink --json
poplink --print
poplink --editor nvim
```

By default, `poplink` scans the last 200 tmux lines. Use `--lines` to override
that for one run, `--history` to search the full tmux scrollback, or `--visible`
to scan only the visible pane.

By default, `poplink` opens regular files only. Use `--include-dirs` if you want
directories in the picker too.

## Config

Create `~/.config/poplink/config.ini` to change defaults:

```ini
[capture]
lines = 300
```

CLI flags take precedence over config.

Supported targets include:

- `/absolute/path/to/file.md`
- `relative/path.ts:42`
- `relative/path.ts:42:8`
- `[markdown link](relative/path.md)`
- Python stack trace lines like `File "app.py", line 20`

## Requirements

- `tmux`
- `fzf`
- Python 3.9+
- `$EDITOR`, or `nvim` on `PATH`

`bat` is optional and used for previews when available.
