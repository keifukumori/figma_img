Minimal Figma JSON → HTML/CSS (n-classes, low transformation)

Usage
- python3 json_to_html.py --json /path/to/figma.json --out dist/minimal
- For full Figma file JSON, add --frame-id <node-id> (e.g., 1:2)

Output
- dist/minimal/<project>/index.html
- dist/minimal/<project>/style.css

Policy
- Preserve nesting (1 node → 1 element), attach .n-<id> to each
- Skip only nodes with visible=false
- Apply SOLID background, simple stroke, corner radius, effects
- Apply auto layout basics (flex-direction, gap, paddings)
- Apply width/height from absoluteBoundingBox when present
- TEXT nodes output <p class="n-..."> with basic typography + color

