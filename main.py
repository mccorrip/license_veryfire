from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse
import requests
import os
import difflib
import spdx_matcher
import sys

app = FastAPI()


def get_base_dir():
    # Check if running as a PyInstaller bundle
    if hasattr(sys, '_MEIPASS'):
        # Use the directory where the executable is located
        return os.path.dirname(sys.executable)
    # Fallback to the script's directory during development
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
LICENSES_DIR = os.path.join(BASE_DIR, "licenses")

if not os.path.exists(LICENSES_DIR):
    raise FileNotFoundError("The licenses folder is missing. Please ensure it is placed next to the executable.")


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, exc: HTTPException):
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css">
        </head>
        <body class="p-5">
            <h1>Error</h1>
            <p class="text-danger">{exc.detail}</p>
            <a href="/" class="btn btn-primary mt-3">Back</a>
        </body>
        </html>
        """,
        status_code=exc.status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def home():
    # Populate dropdown options from the licenses directory
    licenses_dir = "licenses"
    license_files = [f for f in os.listdir(licenses_dir) if os.path.isfile(os.path.join(licenses_dir, f))]
    license_options = "".join([f'<option value="{license_file}">{license_file}</option>' for license_file in license_files])

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css">
    </head>
    <body class="p-5">
        <h1>License Veryfire</h1>
        <form id="licenseForm" method="POST" action="/verify">
            <div class="mb-3">
                <label for="licenseUrl" class="form-label">GitHub License URL</label>
                <input type="url" class="form-control" id="licenseUrl" name="license_url" required>
            </div>
            <div class="mb-3">
                <label for="manualLicense" class="form-label">Select License for Comparison (Optional)</label>
                <select class="form-control" id="manualLicense" name="manual_license">
                    <option value="">Auto Detect</option>
                    {license_options}
                </select>
            </div>
            <button type="submit" class="btn btn-primary">Verify</button>
        </form>
    </body>
    </html>
    """


@app.post("/verify", response_class=HTMLResponse)
async def verify_license(license_url: str = Form(...), manual_license: str = Form(None)):
    # Validate and map the URL
    license_url = validate_and_map_url(license_url)

    # Fetch license text from the validated and mapped URL
    try:
        response = requests.get(license_url)
        response.raise_for_status()
        fetched_license = response.text
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail="Failed to fetch the license. Please check the URL and try again.")

    # Handle manual selection of license
    if manual_license:
        reference_file_path = os.path.join(LICENSES_DIR, manual_license)
        if not os.path.exists(reference_file_path):
            raise HTTPException(status_code=400, detail=f"Reference license '{manual_license}' not found.")
    else:
        # Detect the license using spdx_matcher if manual license is not selected
        licenses_detected, percent = spdx_matcher.analyse_license_text(fetched_license)

        # Check if any licenses were detected
        if not licenses_detected.get("licenses"):
            raise HTTPException(status_code=400, detail="Unable to identify the license type from the provided content.")

        # Extract SPDX ID of the detected license
        spdx_id = next(iter(licenses_detected["licenses"].keys()))  # Get the first SPDX ID

        # Load the corresponding reference license
        reference_file_path = os.path.join(LICENSES_DIR, f"{spdx_id}.txt")
        if not os.path.exists(reference_file_path):
            raise HTTPException(status_code=400, detail=f"Reference license not found for license ID: {spdx_id}.")

    with open(reference_file_path, "r") as f:
        reference_license = f.read()

    # Compare the fetched license with the reference license
    diff = difflib.HtmlDiff().make_table(
        reference_license.splitlines(),
        fetched_license.splitlines(),
        "Reference License",
        "Fetched License",
        context=True,
        numlines=3,
    )

    # Display results
    manual_message = f"Manually Selected License: {manual_license}" if manual_license else f"Detected License: {spdx_id}"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css">
    </head>
    <body class="p-5">
        <h1>License Comparison</h1>
        <h3>{manual_message}</h3>
        <div class="border p-3">{diff}</div>
        <a href="/" class="btn btn-primary mt-3">Back</a>
    </body>
    </html>
    """


def validate_and_map_url(url: str) -> str:
    # Define valid file name patterns for license files
    valid_patterns = ["LICENSE", "LICENCE", "license", "licence"]
    valid_extensions = [".txt", ".md", ""]  # Allow extensions or no extension

    # Check if the URL ends with a valid pattern + extension
    if not any(url.lower().endswith(pattern.lower() + ext) for pattern in valid_patterns for ext in valid_extensions):
        raise HTTPException(
            status_code=400,
            detail="The URL must point to a valid LICENSE file (e.g., LICENSE, LICENCE, license.txt) on GitHub."
        )

    # Map GitHub URL to raw URL if needed
    if "github.com" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("blob/", "")

    return url
