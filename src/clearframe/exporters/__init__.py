"""The clearance report, in the two formats it is delivered in.

`dossier_html` renders it for the browser; `dossier_docx` writes the same
`ClearanceDossier` as a Word document to file with an E&O application.

`safe_cell` lived here and has gone with its only two callers, the marker CSV
and the PRO cue sheet. If a spreadsheet export ever comes back, it comes back
with that guard: labels and owner names come from footage content and open-web
research, and a cell beginning `=`, `+`, `-` or `@` executes as a formula the
moment a coordinator opens the file in Excel.
"""
