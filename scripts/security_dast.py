import httpx
import sys
import time

def run_dast(target_url="http://localhost:8000"):
    """ Runs a simple dynamic scan for common API security misconfigurations. """
    print(f"🚀 [DAST] Probing API at {target_url}...")
    
    issues = []
    
    try:
        with httpx.Client(timeout=10.0) as client:
            # 1. Check for basic connectivity
            resp = client.get(f"{target_url}/health")
            if resp.status_code != 200:
                print(f"❌ [DAST] Target API is unreachable or returned {resp.status_code}")
                return
            
            # 2. Check Security Headers
            print("🔬 Checking Security Headers...")
            headers = resp.headers
            missing_headers = []
            if "X-Content-Type-Options" not in headers: missing_headers.append("X-Content-Type-Options")
            if "X-Frame-Options" not in headers: missing_headers.append("X-Frame-Options")
            if "Content-Security-Policy" not in headers: missing_headers.append("Content-Security-Policy")
            
            if missing_headers:
                issues.append(f"Missing security headers: {', '.join(missing_headers)}")

            # 3. Check for Info Disclosure in /docs (Swagger) or /redoc
            print("🔬 Checking for API Documentation exposure...")
            docs_resp = client.get(f"{target_url}/docs")
            if docs_resp.status_code == 200:
                issues.append("API Docs (/docs) are publicly accessible. Ensure this is intentional (intended for internal use only).")

            # 4. Check for Prometheus Metrics exposure sensitive data
            print("🔬 Probing Metrics endpoint...")
            metric_resp = client.get(f"{target_url}/metrics")
            if metric_resp.status_code == 200:
                print("✅ Metrics endpoint is active.")
            
    except httpx.ConnectError:
        print(f"❌ [DAST] Failed to connect to {target_url}. Is the service running?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ [DAST] Error during scan: {str(e)}")
        sys.exit(1)

    if not issues:
        print("✅ [DAST] No obvious misconfigurations found during simple probe.")
    else:
        print("⚠️ [DAST] Found potential security improvements:")
        for issue in issues:
            print(f"   - {issue}")

if __name__ == "__main__":
    # Default to 8000 (typical uvicorn port)
    run_dast()
