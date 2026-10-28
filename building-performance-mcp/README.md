# Building Performance MCP (Phase 1)

An MCP server that gives Claude early-stage building-performance tools. You describe or upload
a sketch, and Claude reads the dimensions, builds a simple massing model and runs checks. All
the engines are free (Ladybug Tools) and run on your own PC.

| Area | Tools |
|---|---|
| Climate | `load_climate`, `climate_summary`: EPW weather file → temperatures, humidity, solar, degree days, **Indian climate zone (NBC/ECBC)**, ASHRAE zone, monthly table |
| Sun & shading | `sun_position`, `shading_design`: overhang and fin depths for any facade, with advice |
| Solar on facades | `facade_radiation`: kWh/m² on N…NW facades and the roof, for the whole year or a season |
| Massing model | `create_model`, `update_model`, `model_summary`, `list_project_data`: from width × depth or plan coordinates, WWR per orientation, U-values, SHGC, VLT |
| Code checks | `check_envelope`: **ECBC 2017** (ECBC / ECBC+ / SuperECBC), **Eco-Niwas Samhita 2018** (residential), **ASHRAE 90.1-2019** (zones 0–3). `check_lighting_power`: LPD. `show_code_limits` |
| Lighting | `lumen_method`: fixture count, grid layout, spacing, lux, LPD |
| Daylight | `daylight_factor` (BRE average DF), `daylight_depth_check` (limiting room depth) |

Models and loaded climates are saved in `%USERPROFILE%\.bpmcp` (or `~/.bpmcp`), so they are
still there next time. Set `BPMCP_HOME` to use another folder.

## Install on Windows

1. Install **Python 3.10+** from python.org. Tick "Add python.exe to PATH".
2. Get this folder: `git clone https://github.com/pandeykartik658-del/mayank-.git`
   (or download the repo as a ZIP).
3. In PowerShell:

   ```powershell
   cd mayank-\building-performance-mcp
   py -m venv .venv
   .venv\Scripts\pip install -e .
   ```

4. Open Claude Desktop → Settings → Developer → Edit Config. That opens
   `%APPDATA%\Claude\claude_desktop_config.json`. Add the server, using your own path:

   ```json
   {
     "mcpServers": {
       "building-performance": {
         "command": "C:\\Users\\YOU\\mayank-\\building-performance-mcp\\.venv\\Scripts\\python.exe",
         "args": ["-m", "bpmcp"]
       }
     }
   }
   ```

   Keep any servers you already have (such as Revit) in the same `mcpServers` block.
5. Restart Claude Desktop. "building-performance" should appear in the tools/connectors menu.

On macOS or Linux, the command is `.venv/bin/python`.

## Weather files

Download free EPW files from **climate.onebuilding.org**. Go to WMO Region 2 → India and pick
the city; the ISHRAE and TMYx files are good. Give Claude the path to the `.zip` or `.epw`, or
its URL.

## Things to ask Claude

- "Load `C:\climate\IND_RJ_Jaipur...zip` and tell me what climate this is and what it means for my facade design."
- *(upload a sketch)* "Make a model of this: 4 floors at 3.6 m, north is 20° to the right of up, 40% glazing on N and S, 15% on E and W. Wall U 0.4, roof 0.33, glass U 2.8 SHGC 0.25 VLT 0.45. Check it against ECBC."
- "Make option B with SHGC 0.2 and 25% west glazing, and compare the checks."
- "Which facade gets the most sun from March to June? Size an overhang and fins for a 1.5 × 1.2 m west window."
- "Office room 12 × 8 m, 3 m ceiling, 500 lux, 36 W panels at 4000 lm. How many, what layout, what LPD? Does it pass ECBC?"
- "Bedroom 4 × 3.5 m, 2.1 m² of glass VLT 0.6. Is it well daylit? Is it too deep?"

## About the code limits (read this)

The limits are kept in one editable file:
[`src/bpmcp/data/code_limits.json`](src/bpmcp/data/code_limits.json). Each table carries a
`status`:

- **verified**: cross-checked against a published source. So far this covers only the
  ECBC-level roof and wall U-values.
- **unverified**: entered from knowledge of the code but not yet checked against the official
  text. The official BEE and ASHRAE documents couldn't be reached while this was built.

Every check result names which tables are unverified. Before you use a check for a client or
for compliance, compare those values with your copy of ECBC 2017, ENS 2018 or ASHRAE 90.1-2019,
correct them if needed, and change `status` to `verified`. Reinstalling isn't needed; restart
Claude Desktop.

Also note:

- The checks are **prescriptive screening**. They don't replace ECBC/ENS compliance software or
  a whole-building performance submission.
- ASHRAE checks cover **nonresidential** limits in **climate zones 0–3** (all of India falls
  in 0–3).
- ENS RETV and the cold-zone U-envelope aren't calculated yet.
- The lumen method uses a **generic utilisation factor** unless you supply the fitting's UF.
  Use DIALux or Relux for final lighting reports.
- Daylight factor is a room-average formula. Grid-based sDA/ASE comes in Phase 3.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests use synthetic weather files, so they need no downloads.

## Roadmap

| Phase | Adds |
|---|---|
| 1 (this) | Climate, sun and shading, facade radiation, massing model, ECBC/ENS/ASHRAE envelope and LPD checks, lumen method, daylight factor |
| 2 | EnergyPlus/OpenStudio energy runs: EUI, end uses, peak cooling (TR), option comparison |
| 3 | Radiance daylight (DF grids, sDA/ASE, glare) and IES-based lighting calculations |
| 4 | Importers: gbXML (Revit), IFC (FreeCAD/Bonsai), Speckle |
| 5 | HTML/Excel/PDF reports with charts |
