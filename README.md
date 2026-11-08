# FFgrab for Fitgirl

FFgrab is a small Python script that turns links from `fuckingfast.co` and related hosts into direct download links.

It is built for the common case where the page loads a Cloudflare challenge and the actual file link is hidden behind a redirect flow.

## What it does

- Reads a list of page URLs from an input file
- Tries a fast HTTP-only resolution first
- Falls back to a real browser (Playwright) when Cloudflare blocks the request
- Writes the resolved direct links to an output file

## Project files

- `grabber.py` — main script
- `requirements.txt` — Python dependencies
- `fflinks.txt` — example input file with one link per line
- `ddlinks.txt` — output file created after running the script

## Install

1. Open a terminal in the project folder.
2. Install the dependencies:

```bash
pip install -r requirements.txt
```

3. If Playwright is not already installed, set up the browser runtime:

```bash
python -m playwright install chromium
```

## Usage

Run the script with your input and output files:

```bash
python grabber.py
```

This uses the default files:

- input: `fflinks.txt`
- output: `ddlinks.txt`

Or specify your own files:

```bash
python grabber.py input.txt output.txt
```

## Input format

Put one URL per line in the input file.

Example:

```text
https://fuckingfast.co/abc123
https://fuckingfast.co/abc124
```

Empty lines and comment lines starting with `#` are ignored.

## Output format

The script writes one resolved direct download URL per line to the output file.

Example:

```text
https://example.com/download/file.zip
https://example.com/download/another-file.rar
```

## Notes

- The script handles Cloudflare challenges automatically using a browser fallback when needed.
- If a link cannot be resolved, it prints an error and continues with the rest of the list instead of crashing the whole batch.
- This tool is intended for downloading files from supported link-hosting pages and should be used only in accordance with the destination site's terms and local law.

## Troubleshooting

If the script reports that Playwright is missing:

```bash
pip install playwright
python -m playwright install chromium
```

If the browser fallback still fails, make sure the page is reachable and not blocked by a site-specific anti-bot change.
