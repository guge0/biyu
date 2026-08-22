param([Parameter(Mandatory = $true)][string]$Message)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Biyu'
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ClientSize = New-Object System.Drawing.Size(780, 300)
$form.MinimumSize = New-Object System.Drawing.Size(640, 280)
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.ShowInTaskbar = $true
$form.TopMost = $true

$layout = New-Object System.Windows.Forms.TableLayoutPanel
$layout.Dock = [System.Windows.Forms.DockStyle]::Fill
$layout.Padding = New-Object System.Windows.Forms.Padding(24)
$layout.RowCount = 2
$layout.ColumnCount = 1
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 46)))

$text = New-Object System.Windows.Forms.TextBox
$text.Multiline = $true
$text.ReadOnly = $true
$text.WordWrap = $true
$text.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$text.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$text.BackColor = [System.Drawing.Color]::White
$text.Font = New-Object System.Drawing.Font('Segoe UI', 11)
$text.Dock = [System.Windows.Forms.DockStyle]::Fill
$text.Text = $Message
$text.TabStop = $false

$button = New-Object System.Windows.Forms.Button
$button.Text = 'OK'
$button.Width = 96
$button.Height = 32
$button.Anchor = [System.Windows.Forms.AnchorStyles]::Right
$button.DialogResult = [System.Windows.Forms.DialogResult]::OK

$layout.Controls.Add($text, 0, 0)
$layout.Controls.Add($button, 0, 1)
$form.Controls.Add($layout)
$form.AcceptButton = $button
$form.CancelButton = $button
$form.Add_Shown({
    $form.Activate()
    $form.BringToFront()
})
[void]$form.ShowDialog()
