from ui.terminal import shell_line, terminal_argv


def test_mac_escapes_for_applescript():
    argv = terminal_argv(["/a b/steamcmd.sh", "+login", 'we"ird'], "mac")
    assert argv[0] == "osascript" and 'do script "' in argv[2]
    assert '\\"' in argv[2] and "'/a b/steamcmd.sh'" in argv[2]


def test_win_and_other():
    assert terminal_argv(["steamcmd.exe", "+login", "u"], "win")[-1] == "steamcmd.exe +login u"
    assert terminal_argv(["x"], "linux") is None
    assert shell_line(["a", "b c"], "linux") == "a 'b c'"
