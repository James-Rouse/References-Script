import os
import re
import requests
import time
import csv
from pathlib import Path
from Bio import Entrez
from tqdm import tqdm

# Constants
CROSSREF_API = 'https://api.crossref.org/works'
UNPAYWALL_BASE = 'https://api.unpaywall.org/v2/'
UNPAYWALL_EMAIL = 'james.thomas.rouse@gmail.com'  # Replace with your actual email
DELAY = 1  # seconds between API requests
TIMEOUT = 10  # seconds for API request timeout
MAX_RETRIES = 3  # Maximum number of retries for API requests

# Entrez configuration
NCBI_EMAIL = "james.thomas.rouse@gmail.com"  # Replace with your actual email
Entrez.email = NCBI_EMAIL

# Directories
BASE_DIR = Path(__file__).parent
REFS_DIR = BASE_DIR / "references"
OUTPUT_DIR = BASE_DIR / "full_texts"
REFS_FILE = REFS_DIR / "scrupulosity_references.txt"
RESULTS_FILE = OUTPUT_DIR / "results.csv"

# Headers for HTTP requests
HEADERS = {
    'User-Agent': 'ReferencesSearch/1.0 (mailto:james.thomas.rouse@gmail.com)'
}

def extract_doi(reference):
    """
    Extract DOI from a reference using regex.
    Returns the DOI string if found, else None.
    """
    doi_pattern = r'(10.\d{4,9}/[-._;()/:A-Z0-9]+)'
    match = re.search(doi_pattern, reference, re.IGNORECASE)
    return match.group(1) if match else None

def read_references(file_path=REFS_FILE):
    """Read references from text file with detailed debugging."""
    try:
        path = Path(file_path).resolve()
        print(f"Attempting to read: {path}")
        
        if not path.exists():
            print(f"File not found: {path}")
            return []
            
        with open(path, 'r', encoding='utf-8') as file:
            references = [line.strip() for line in file if line.strip()]
            
        print(f"Found {len(references)} references")
        if references:
            print("First reference:", references[0][:50], "...")
        
        return references
            
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return []

def search_crossref(title):
    """Search CrossRef API for reference and return DOI."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"Searching CrossRef for: {title[:50]}...")
            params = {
                'query.bibliographic': title,
                'rows': 1
            }
            
            response = requests.get(
                CROSSREF_API,
                params=params,
                headers=HEADERS,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            time.sleep(DELAY)  # Respect rate limiting
            
            if data['message']['items']:
                result = data['message']['items'][0]
                doi = result.get('DOI')
                found_title = result.get('title', [''])[0]
                print(f"Found DOI: {doi} for title: {found_title[:50]}...")
                return doi
            else:
                print(f"No DOI found for: {title}")
                return None
                
        except requests.Timeout:
            print(f"CrossRef request timed out for: {title}. Attempt {attempt}/{MAX_RETRIES}")
        except requests.RequestException as e:
            print(f"CrossRef HTTP error for '{title}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        except ValueError as e:
            print(f"CrossRef JSON decoding failed for '{title}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        except Exception as e:
            print(f"Unexpected error in CrossRef search for '{title}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        
        if attempt < MAX_RETRIES:
            print("Retrying...")
            time.sleep(DELAY)
        else:
            print("Max retries reached. Moving to next reference.")
            return None

def get_unpaywall_pdf_url(doi):
    """Use Unpaywall API to get open access PDF URL."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            url = f"{UNPAYWALL_BASE}{doi}"
            params = {'email': UNPAYWALL_EMAIL}
            response = requests.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            time.sleep(DELAY)  # Respect rate limiting
            
            if data.get('is_oa') and data.get('best_oa_location'):
                # Prefer 'url_for_pdf' if available
                pdf_url = data['best_oa_location'].get('url_for_pdf') or data['best_oa_location'].get('url')
                if pdf_url:
                    print(f"Found Unpaywall PDF URL: {pdf_url}")
                    return pdf_url
            print(f"No Open Access PDF found via Unpaywall for DOI: {doi}")
            return None
        except requests.Timeout:
            print(f"Unpaywall request timed out for DOI: {doi}. Attempt {attempt}/{MAX_RETRIES}")
        except requests.RequestException as e:
            print(f"Unpaywall HTTP error for DOI '{doi}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        except ValueError as e:
            print(f"Unpaywall JSON decoding failed for DOI '{doi}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        except Exception as e:
            print(f"Unexpected error in Unpaywall search for DOI '{doi}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        
        if attempt < MAX_RETRIES:
            print("Retrying...")
            time.sleep(DELAY)
        else:
            print("Max retries reached. Moving to next reference.")
            return None

def download_pdf(pdf_url, filename):
    """Download PDF from URL and save to filename."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(response.content)
            print(f"Saved: {filename}")
            return True
        except requests.Timeout:
            print(f"Download timed out for: {pdf_url}. Attempt {attempt}/{MAX_RETRIES}")
        except requests.RequestException as e:
            print(f"HTTP error while downloading '{pdf_url}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        except Exception as e:
            print(f"Unexpected error while downloading '{pdf_url}': {str(e)}. Attempt {attempt}/{MAX_RETRIES}")
        
        if attempt < MAX_RETRIES:
            print("Retrying...")
            time.sleep(DELAY)
        else:
            print("Max retries reached. Failed to download PDF.")
            return False

def save_results(results, output_file=RESULTS_FILE):
    """Save all results to a CSV file."""
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['reference', 'DOI', 'Retrieved', 'Source']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"Results saved to {output_file}")
    except Exception as e:
        print(f"Error saving results to CSV: {str(e)}")

def main():
    """Main function to process references."""
    # Ensure directories exist
    REFS_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Check file existence
    if not REFS_FILE.exists():
        print(f"References file not found at: {REFS_FILE}")
        print("Please create the file with your references.")
        return
    
    # Read references
    print("\nReading references...")
    references = read_references()
    if not references:
        print("No references found. Ensure the file is not empty.")
        return
    
    # Process each reference
    results = []
    for ref in tqdm(references, desc="Processing references"):
        ref = ref.strip()
        if not ref:
            continue
        
        # Extract DOI if present
        doi = extract_doi(ref)
        if doi:
            print(f"Extracted DOI from reference: {doi}")
        else:
            # Search CrossRef for DOI
            doi = search_crossref(ref)
        
        if not doi:
            results.append({
                "reference": ref,
                "DOI": "",
                "Retrieved": False,
                "Source": "No DOI found"
            })
            continue
        
        # Fetch PDF URL from Unpaywall
        pdf_url = get_unpaywall_pdf_url(doi)
        if not pdf_url:
            results.append({
                "reference": ref,
                "DOI": doi,
                "Retrieved": False,
                "Source": "No OA PDF found"
            })
            continue
        
        # Define safe filename
        safe_ref = re.sub(r'[\\/*?:"<>|]', "_", ref)
        filename = OUTPUT_DIR / f"{safe_ref}.pdf"
        
        # Download PDF
        success = download_pdf(pdf_url, filename)
        results.append({
            "reference": ref,
            "DOI": doi,
            "Retrieved": success,
            "Source": "Unpaywall" if success else "Download Failed"
        })
    
    # Save results
    save_results(results)
    print("\nAll references processed.")

if __name__ == "__main__":
    main()