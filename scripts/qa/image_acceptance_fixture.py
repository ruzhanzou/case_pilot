"""Create a deterministic screenshot fixture for real multimodal acceptance."""

import sys
from pathlib import Path

import pymupdf

destination = Path(sys.argv[1])
destination.parent.mkdir(parents=True, exist_ok=True)
svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760">
  <rect width="1200" height="760" fill="#f4f7fb"/>
  <rect x="90" y="70" width="1020" height="620" rx="24" fill="white" stroke="#b7c5d8" stroke-width="3"/>
  <text x="145" y="145" font-family="Arial" font-size="42" font-weight="bold" fill="#17324d">Password reset</text>
  <text x="145" y="215" font-family="Arial" font-size="28" fill="#344b63">Account email</text>
  <rect x="145" y="240" width="690" height="70" rx="10" fill="#f8fafc" stroke="#8ba0b8" stroke-width="2"/>
  <text x="175" y="285" font-family="Arial" font-size="25" fill="#61758b">user@example.com</text>
  <rect x="145" y="345" width="330" height="76" rx="12" fill="#1769aa"/>
  <text x="190" y="394" font-family="Arial" font-size="27" font-weight="bold" fill="white">Send reset link</text>
  <rect x="145" y="465" width="910" height="150" rx="14" fill="#fff4e5" stroke="#f0a33a" stroke-width="2"/>
  <text x="185" y="515" font-family="Arial" font-size="29" font-weight="bold" fill="#70400b">Current production rules</text>
  <text x="185" y="560" font-family="Arial" font-size="26" fill="#503514">Link expires after exactly 300 seconds.</text>
  <text x="185" y="602" font-family="Arial" font-size="26" fill="#503514">Expired link returns E731. Do not issue a new link.</text>
</svg>"""
document = pymupdf.open(stream=svg.encode(), filetype="svg")
pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
pixmap.save(destination)
