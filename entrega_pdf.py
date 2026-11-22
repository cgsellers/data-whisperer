#!/usr/bin/env python3
"""Genera PDF desde markdown usando weasyprint"""
import markdown
from weasyprint import HTML, CSS
from pathlib import Path

# Leer markdown
md_path = Path("/Users/carlos/code/fcc/ENTREGA_PLATAFORMA_AGENTICA.md")
with open(md_path, "r", encoding="utf-8") as f:
    md_content = f.read()

# Convertir a HTML
html_content = markdown.markdown(
    md_content,
    extensions=[
        'tables', 'fenced_code', 'codehilite', 'toc',
        'attr_list', 'def_list', 'footnotes'
    ],
    extension_configs={
        'codehilite': {'css_class': 'highlight'},
    }
)

# CSS para PDF profesional
css = CSS(string='''
@page {
    size: A4;
    margin: 2.5cm 2cm;
    @top-center { content: "Plataforma Agéntica de Datos - Entrega Técnica"; font-size: 9pt; color: #666; }
    @bottom-center { content: "Página " counter(page) " de " counter(pages); font-size: 9pt; color: #666; }
    @bottom-right { content: "Confidencial - MVP v1.0"; font-size: 8pt; color: #999; }
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #222;
    max-width: none;
}

h1 {
    font-size: 24pt;
    color: #1a1a2e;
    border-bottom: 3px solid #2563eb;
    padding-bottom: 0.3em;
    margin-top: 2em;
    page-break-before: always;
}
h1:first-of-type { page-break-before: auto; margin-top: 0; }

h2 {
    font-size: 18pt;
    color: #1e3a5f;
    border-bottom: 1px solid #d1d5db;
    padding-bottom: 0.2em;
    margin-top: 1.5em;
}

h3 {
    font-size: 14pt;
    color: #2563eb;
    margin-top: 1.2em;
}

h4 {
    font-size: 12pt;
    color: #374151;
    margin-top: 1em;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #d1d5db;
    padding: 6px 10px;
    text-align: left;
}

th {
    background-color: #f3f4f6;
    font-weight: 600;
    color: #1f2937;
}

tr:nth-child(even) td { background-color: #fafafa; }

code {
    font-family: "SF Mono", "Fira Code", "Monaco", Consolas, monospace;
    font-size: 9pt;
    background-color: #f3f4f6;
    padding: 2px 5px;
    border-radius: 3px;
}

pre {
    background-color: #1e1e1e;
    color: #d4d4d4;
    padding: 1em;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 8.5pt;
    line-height: 1.5;
    page-break-inside: avoid;
}

pre code {
    background: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

.highlight { background: #1e1e1e; }

.blockquote, blockquote {
    border-left: 4px solid #2563eb;
    padding-left: 1em;
    margin: 1em 0;
    color: #4b5563;
    font-style: italic;
}

hr { border: none; border-top: 1px solid #e5e7eb; margin: 2em 0; }

ul, ol { padding-left: 1.5em; }
li { margin: 0.3em 0; }

a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Evitar cortes feos */
h1, h2, h3, h4, table, pre, blockquote { page-break-inside: avoid; }
h1, h2, h3 { page-break-after: avoid; }

/* Primera página - portada */
.cover {
    text-align: center;
    padding-top: 8cm;
    page-break-after: always;
}
.cover h1 { border: none; font-size: 36pt; margin: 0; }
.cover .subtitle { font-size: 18pt; color: #666; margin-top: 1em; }
.cover .meta { margin-top: 3em; font-size: 12pt; color: #888; }

.toc { page-break-after: always; }
.toc ul { list-style: none; padding-left: 0; }
.toc li { margin: 0.5em 0; }
.toc a { text-decoration: none; color: #1e3a5f; }
''')

# Insertar portada al inicio
cover_html = '''
<div class="cover">
    <h1>Plataforma Agéntica de Datos</h1>
    <div class="subtitle">Entrega Técnica - MVP v1.0</div>
    <div class="meta">
        <p><strong>Fecha:</strong> 2026-11-19</p>
        <p><strong>Autor:</strong> Carlos Sellers</p>
        <p><strong>Stack:</strong> Python 3.11, FastAPI, PostgreSQL 16, Redis 7, Docker Compose, LLM (OpenAI/Anthropic)</p>
    </div>
</div>
'''

full_html = f'''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Plataforma Agéntica de Datos - Entrega Técnica</title>
</head>
<body>
{cover_html}
{html_content}
</body>
</html>
'''

# Generar PDF
output_path = Path("/Users/carlos/code/fcc/ENTREGA_PLATAFORMA_AGENTICA.pdf")
HTML(string=full_html).write_pdf(str(output_path), stylesheets=[css])
print(f"✅ PDF generado: {output_path}")
print(f"   Tamaño: {output_path.stat().st_size / 1024:.1f} KB")