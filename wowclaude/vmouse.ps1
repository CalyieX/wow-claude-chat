# Background mouse and keyboard for the game window: posts window messages, so the player's own mouse and focus stay untouched.
# Called by wowclaude:  powershell -File vmouse.ps1 -Action click|type -Title "World of Warcraft" -X 100 -Y 200 [-Button L|R|M] | -Text "..."
param([string]$Action, [string]$Title = "World of Warcraft", [int]$X = 0, [int]$Y = 0, [string]$Button = "L", [string]$Text = "")
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class VM {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc e, IntPtr p);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static IntPtr Find(string title) {
    foreach (var c in new string[] { "GxWindowClass", "GxWindowClassD3d" }) { IntPtr g = FindWindow(c, null); if (g != IntPtr.Zero) return g; }  // the game itself, never a browser page titled like it
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, p) => { if (!IsWindowVisible(h)) return true; var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
      if (sb.ToString().StartsWith(title)) { found = h; return false; } return true; }, IntPtr.Zero);
    return found;
  }
}
"@
$h = [VM]::Find($Title)
if ($h -eq [IntPtr]::Zero) { Write-Error "game window not found"; exit 2 }
function Post($m, $w, $l) { [void][VM]::PostMessage($h, [uint32]$m, [IntPtr]$w, [IntPtr]$l) }
if ($Action -eq "click") {
  $lp = ($Y -shl 16) -bor ($X -band 0xFFFF)
  $down, $up, $mk = switch ($Button.ToUpper()) { "R" { 0x204, 0x205, 2 } "M" { 0x207, 0x208, 16 } default { 0x201, 0x202, 1 } }
  Post 0x200 0 $lp; Start-Sleep -Milliseconds 40
  Post $down $mk $lp; Start-Sleep -Milliseconds 60; Post $up 0 $lp
} elseif ($Action -eq "type") {
  $keys = @{ "{Enter}" = 0x0D; "{Esc}" = 0x1B; "{Tab}" = 0x09; "{Backspace}" = 0x08 }
  $i = 0
  while ($i -lt $Text.Length) {
    $rest = $Text.Substring($i); $hit = $keys.Keys | Where-Object { $rest.StartsWith($_) } | Select-Object -First 1
    if ($hit) { $vk = $keys[$hit]; Post 0x100 $vk 0; Start-Sleep -Milliseconds 20; if ($vk -eq 0x0D) { Post 0x102 13 0 }; Post 0x101 $vk 0; $i += $hit.Length }
    else { Post 0x102 ([int][char]$Text[$i]) 0; $i++ }
    Start-Sleep -Milliseconds 15
  }
} else { Write-Error "unknown action"; exit 3 }
