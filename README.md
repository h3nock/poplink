# poplink

Open file paths from your current tmux or Rex pane without touching the mouse.

`poplink` captures pane text, extracts local file paths and file locations, lets
you choose one with `fzf`, then opens it in your editor.

## Install

For local development:

```sh
git clone https://github.com/h3nock/poplink.git ~/poplink
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

By default, `poplink` scans recent output (200 lines). Use `--lines` to override
that for one run, `--history` to search the full scrollback, or `--visible`
to scan only the visible pane.

By default, `poplink` opens regular files only. Use `--include-dirs` if you want
directories in the picker too.

## Rex

Run `poplink` inside a Rex terminal to capture that block. When running inside
tmux nested in Rex, tmux takes priority. Use `--backend rex` to override that,
or `--block BLOCK_ID` to capture a particular Rex source block.

A floating picker must receive the **original block ID**, because its own
`REX_BLOCK` identifies the new picker terminal. The Rex configuration in
`henok3878/dotfiles` binds this to `Ctrl+A o`. It starts
`~/poplink/bin/poplink --backend rex --block SOURCE_BLOCK --hold-on-error`
inside a floating terminal. Set `POPLINK_BIN` if you clone this repo elsewhere.

Rex capture uses `REX_SERVER` and `REX_SESSION` from the terminal environment.
Relative file paths are resolved against the source block's foreground working
directory. It reads the source explicitly rather than whichever pane is focused
when the picker opens. File opening runs on the same host as the picker.

Neovim launches with `-i NONE` so short-lived picker editors do not read or write
the shared ShaDa history. An explicit `-i` option in `--editor` or `$EDITOR`
takes precedence.

`--history` captures all retained output. `--lines N` scans the last N logical
lines after joining soft wraps. Rex currently returns the full scrollback before
poplink limits it locally. `--visible` remains tmux-only: Rex does not expose the
boundary between history and the visible screen in its text capture.

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

- `tmux` or `rex` (Rex adds its CLI to terminal PATH)
- `fzf`
- Python 3.9+
- `$EDITOR`, or `nvim` on `PATH`

`bat` is optional and used for previews when available.
