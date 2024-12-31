import os
import re
import requests
import time
import csv
import hashlib
import warnings
import urllib3
from pathlib import Path
from Bio import Entrez
from tqdm import tqdm
import xml.etree.ElementTree as ET
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings
warnings.simplefilter('ignore', InsecureRequestWarning)

# Constants
CROSSREF_API = 'https://api.crossref.org/works'
UNPAYWALL_BASE = 'https://api.unpaywall.org/v2/'
UNPAYWALL_EMAIL = 'james.thomas.rouse@gmail.com'
DELAY = 2  # Increased delay between requests
TIMEOUT = 15  # Increased timeout
MAX_RETRIES = 3
MAX_FILENAME_LENGTH = 100
CORE_API_KEY = 'your_core_api_key'

# Entrez configuration
NCBI_EMAIL = "james.thomas.rouse@gmail.com"
Entrez.email = NCBI_EMAIL

# Directories
BASE_DIR = Path(__file__).parent
REFS_DIR = BASE_DIR / "references"
OUTPUT_DIR = BASE_DIR / "full_texts"
REFS_FILE = REFS_DIR / "scrupulosity_references.txt"
RESULTS_FILE = OUTPUT_DIR / "results.csv"

# Headers
HEADERS = {
    'User-Agent': 'ReferencesSearch/1.0 (mailto:james.thomas.rouse@gmail.com)'
}

def exponential_backoff(attempt):
    """Calculate delay with exponential backoff."""
    return DELAY * (2 ** attempt)

def get_safe_filename(reference, doi):
    """Create safe filename from reference and DOI."""
    # Create base filename from reference
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", reference)
    safe_name = safe_name[:MAX_FILENAME_LENGTH]
    
    # Add hash of full reference to ensure uniqueness
    name_hash = hashlib.md5(reference.encode()).hexdigest()[:8]
    
    return f"{safe_name}_{name_hash}.pdf"

def extract_doi(reference):
    """Extract DOI from reference."""
    doi_pattern = r'(10.\d{4,9}/[-._;()/:A-Z0-9]+)'
    match = re.search(doi_pattern, reference, re.IGNORECASE)
    return match.group(1).lower() if match else None

def read_references(file_path=REFS_FILE):
    """Read references from file."""
    try:
        path = Path(file_path).resolve()
        print(f"Reading: {path}")
        
        if not path.exists():
            print(f"File not found: {path}")
            return []
            
        with open(path, 'r', encoding='utf-8') as file:
            references = [line.strip() for line in file if line.strip()]
            
        print(f"Found {len(references)} references")
        return references
            
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='cp1252', errors='replace') as file:
                references = [line.strip() for line in file if line.strip()]
            print(f"Found {len(references)} references (cp1252 encoding)")
            return references
        except Exception as e:
            print(f"Failed to read references: {e}")
            return []
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

def search_crossref(title):
    """Search CrossRef API for DOI."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Searching CrossRef for DOI: {title[:50]}...")
            params = {'query.bibliographic': title, 'rows': 1}
            
            response = requests.get(
                CROSSREF_API,
                params=params,
                headers=HEADERS,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            
            if data['message']['items']:
                result = data['message']['items'][0]
                doi = result.get('DOI', '').lower()
                return doi
            return None
                
        except Exception as e:
            print(f"CrossRef Error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(exponential_backoff(attempt))
            else:
                return None

def get_unpaywall_pdf_url(doi):
    """Get PDF URL from Unpaywall."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Searching Unpaywall for PDF: {doi}")
            url = f"{UNPAYWALL_BASE}{doi}"
            params = {'email': UNPAYWALL_EMAIL}
            response = requests.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            if data.get('is_oa') and data.get('best_oa_location'):
                pdf_url = (data['best_oa_location'].get('url_for_pdf') or 
                          data['best_oa_location'].get('url'))
                if pdf_url:
                    return pdf_url
            return None
            
        except Exception as e:
            print(f"Unpaywall Error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(exponential_backoff(attempt))
            else:
                return None

def search_pmc(doi):
    """Search PubMed Central for PDF."""
    try:
        print(f"Searching PMC for PDF: {doi}")
        url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=xml"
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        article = root.find('record')
        
        if article is not None and article.find('pmcid') is not None:
            pmcid = article.find('pmcid').text
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
            return pdf_url
        return None
        
    except Exception as e:
        print(f"PMC Error: {e}")
        return None

def search_core(doi):
    """Search CORE for PDF."""
    try:
        print(f"Searching CORE for PDF: {doi}")
        url = f"https://core.ac.uk:443/api-v2/articles/doi/{doi}"
        headers = {'Authorization': f'Bearer {CORE_API_KEY}'}
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        if data.get('fullTextUrl'):
            pdf_url = data['fullTextUrl']
            return pdf_url
        return None
        
    except Exception as e:
        print(f"CORE Error: {e}")
        return None

def get_pdf_url(doi):
    """Try multiple sources for PDF URL."""
    # Try Unpaywall
    pdf_url = get_unpaywall_pdf_url(doi)
    if (pdf_url):
        return pdf_url
    
    time.sleep(DELAY)
    
    # Try PMC
    pdf_url = search_pmc(doi)
    if (pdf_url):
        return pdf_url
    
    time.sleep(DELAY)
    
    # Try CORE
    pdf_url = search_core(doi)
    return pdf_url

def download_pdf(pdf_url, filename):
    """Download PDF with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                pdf_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                verify=False  # Disable SSL verification
            )
            response.raise_for_status()
            
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
            
        except Exception as e:
            print(f"Download Error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(exponential_backoff(attempt))
            else:
                return False

def save_results(results):
    """Save results to CSV."""
    try:
        with open(RESULTS_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['reference', 'DOI', 'Retrieved', 'Source'])
            writer.writeheader()
            writer.writerows(results)
        print(f"Results saved to {RESULTS_FILE}")
    except Exception as e:
        print(f"Error saving results: {e}")

def main():
    """Main function."""
    # Create directories
    REFS_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Read references
    references = read_references()
    if not references:
        return
    
    results = []
    for ref in tqdm(references, desc="Processing references"):
        try:
            # Get DOI
            doi = extract_doi(ref) or search_crossref(ref)
            if not doi:
                results.append({
                    "reference": ref,
                    "DOI": "",
                    "Retrieved": False,
                    "Source": "No DOI found"
                })
                continue
            
            # Get PDF URL
            pdf_url = get_pdf_url(doi)
            if not pdf_url:
                results.append({
                    "reference": ref,
                    "DOI": doi,
                    "Retrieved": False,
                    "Source": "No PDF found"
                })
                continue
            
            # Download PDF
            filename = OUTPUT_DIR / get_safe_filename(ref, doi)
            success = download_pdf(pdf_url, filename)
            
            if success:
                source = "PDF Retrieved"
                print(f"Success: {filename.name}")
            else:
                source = "Download Failed"
                print(f"Failed: {filename.name}")

            results.append({
                "reference": ref,
                "DOI": doi,
                "Retrieved": success,
                "Source": source
            })
            
            time.sleep(DELAY)
            
        except Exception as e:
            print(f"Processing Error: {e}")
            results.append({
                "reference": ref,
                "DOI": doi if 'doi' in locals() else "",
                "Retrieved": False,
                "Source": f"Error: {str(e)}"
            })
    
    # Save results
    save_results(results)

if __name__ == "__main__":
    main()