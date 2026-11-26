# Laptop special keys

Some laptop keys never reach Qtile under their printed name. This guide shows
how to find out what a key sends and how to bind it. The examples come from a
Lenovo Ideapad, but the steps work on any distro with systemd.

## Find out what the key sends

Check two levels, X11 first:

```bash
xev -event keyboard
```

Press the key. If `xev` prints a `keycode`, X sees the key and Qtile can bind
it. If `xev` prints nothing, check the kernel level (on Ubuntu,
`sudo apt install libinput-tools` first):

```bash
sudo libinput debug-events --show-keycodes
```

| `libinput` | `xev` | Meaning | Fix |
|---|---|---|---|
| nothing | nothing | The firmware handles the key itself | None |
| `KEY_XXX (N)` | nothing | The kernel code `N` is above 247, and X11 drops keycodes above 255 (`N + 8`) | [Remap it with hwdb](#remap-a-key-x11-cannot-see) |
| `KEY_XXX (N)` | a keycode | X sees the key | [Bind it in Qtile](#bind-a-key-x11-can-see) |

## Bind a key X11 can see

Use the keysym `xev` prints, as in any other `Key`. If Qtile's keysym table
does not know the name, reloading fails with `Unknown keysym` and **every**
binding stops working. In that case, pass the keycode as an integer instead.

### The Copilot key

The Copilot key has no code of its own. The firmware sends **Super + Shift +
F23**. X11 maps F23 to keycode 201, whose Shift level is `XF86Assistant`, so
`screenkey` shows `Super + XF86Assistant` and hides the Shift.

Qtile has no `XF86Assistant` keysym, and Shift is really held, so the binding
needs both modifiers and the raw keycode:

```python
Key([mod, "shift"], 201, lazy.spawn("rofi -show drun"), desc="Rofi App Launcher (Copilot key)"),
```

[`src/modules/keys.py`](../../src/modules/keys.py) ships this binding.

## Remap a key X11 cannot see

Tell the kernel to send a key with a low code instead, using a udev hwdb rule.

1. Get the key's scancode and the input device's name. Run `sudo evtest`, pick
   the device, and press the key:

   ```text
   Event: ... type 4 (EV_MSC), code 4 (MSC_SCAN), value 101
   Event: ... type 1 (EV_KEY), code 364 (KEY_FAVORITES), value 1
   ```

   The `MSC_SCAN` value (`101` here) is the scancode. Special keys often come
   from a separate device, such as `Ideapad extra buttons`, not from the main
   keyboard. `grep -B5 "eventN " /proc/bus/input/devices` prints the name of
   `/dev/input/eventN`.

2. Pick a kernel key whose X11 keysym you want. X11 keycode = kernel code + 8,
   and `xmodmap -pke` lists every X11 keycode with its keysyms. For example,
   `XF86Favorites` is X11 keycode 164, which is kernel code 156,
   `KEY_BOOKMARKS`.

3. Write the rule. The second line must start with a space, and the key name is
   the lowercase kernel name without `KEY_`:

   ```bash
   sudo tee /etc/udev/hwdb.d/90-ideapad-favorites.hwdb <<'EOF'
   evdev:name:Ideapad extra buttons:*
    KEYBOARD_KEY_101=bookmarks
   EOF
   ```

   The rule matches the device by name, so it keeps working if the `eventN`
   number changes after a reboot.

4. Apply it:

   ```bash
   sudo systemd-hwdb update
   sudo udevadm trigger --sysname-match="event*"
   ```

5. Press the key in `xev -event keyboard`. It now prints
   `keycode 164 (keysym 0x1008ff30, XF86Favorites)`. If it does not, reboot and
   try again.

This config already binds `XF86Favorites` to the rofi app menu, so on that
Ideapad `Fn + F9` opens rofi with no Qtile change.
