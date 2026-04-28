param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [Parameter(Mandatory = $true)]
    [string]$SignalFile,

    [int]$MinimumMilliseconds = 3000
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$start = Get-Date
$image = [System.Drawing.Image]::FromFile($ImagePath)
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$maxWidth = [Math]::Min(960, [Math]::Floor($screen.Width * 0.72))
$maxHeight = [Math]::Min(540, [Math]::Floor($screen.Height * 0.72))
$scale = [Math]::Min($maxWidth / $image.Width, $maxHeight / $image.Height)
$width = [Math]::Max(1, [Math]::Floor($image.Width * $scale))
$height = [Math]::Max(1, [Math]::Floor($image.Height * $scale))

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.ClientSize = New-Object System.Drawing.Size($width, $height)
$form.BackColor = [System.Drawing.Color]::White

$picture = New-Object System.Windows.Forms.PictureBox
$picture.Dock = [System.Windows.Forms.DockStyle]::Fill
$picture.Image = $image
$picture.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::StretchImage
$form.Controls.Add($picture)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100
$timer.Add_Tick({
    $elapsed = ((Get-Date) - $start).TotalMilliseconds
    if ((Test-Path -LiteralPath $SignalFile) -and $elapsed -ge $MinimumMilliseconds) {
        $timer.Stop()
        $form.Close()
    }
})

$form.Add_Shown({ $timer.Start() })
$form.Add_FormClosed({
    $timer.Dispose()
    $picture.Dispose()
    $image.Dispose()
})

[System.Windows.Forms.Application]::Run($form)
