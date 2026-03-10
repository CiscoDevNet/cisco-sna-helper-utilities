## Dev environment tips

- **Python version**: Use Python 3.13+.
- **Virtual env (recommended)**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -U pip
  ```
- **Each helper utility is standalone**: cd into a helper utility directory, read its `README.md`, install that folder’s `requirements.txt` if present, then run the script. Ask for approval before running the script, including indicating what arguments you will provide.
- **Install dependencies (pattern)**:
  ```bash
  cd <helper-utility-folder>
  [ -f requirements.txt ] && python -m pip install -r requirements.txt
  ```

### Quick run examples

- **cert_rotation_client**
  ```bash
  cd cert_rotation_client
  python -m pip install -r requirements.txt
  export REQUESTS_CA_BUNDLE=<path-to-root-CA-cert>
  export USERNAME=<username>
  export PASSWORD=<password>
  python update-identity.py -m <manager-address> -f <certificate-pfx-bundle> -p <pfx-password> --fqdns <selected-appliances>
  ```

- **truststore_client**
  ```bash
  cd cert_rotation_client
  python -m pip install -r requirements.txt
  export REQUESTS_CA_BUNDLE=<path-to-root-CA-cert>
  export USERNAME=<username>
  export PASSWORD=<password>
  python update-truststores.py -m <manager-address> -f <pem-certificate-to-check> --fqdns all --action check
  ```

## Testing instructions

- **There is no test suite** yet in this repository.
- **Static checks (optional)**: If you add new Python code, you can run lightweight checks:
  ```bash
  python -m pip install ruff mypy
  ruff check .
  mypy --ignore-missing-imports .
  ```

- **Test the code with the Cisco DevNet sandbox**
  Visit https://devnetsandbox.cisco.com/DevNet to book a related sandbox

- **Latest Cisco API documentation**:
  https://developer.cisco.com/docs/. Note that some of the helper utilities use APIs that have not yet been publicly documented.


## PR instructions

- **Title format**: `[helper-utility-folder] <Short description>` (e.g., `[cert_rotation_client] added dry run option`).
- **Scope**: Keep changes limited to one folder when possible. If you cross-cut multiple folders, explain why in the PR description.
- **Before committing**:
  - If you added deps, include or update that folder’s `requirements.txt`.
  - Update `README.md` within the affected folder.
  - Run optional linters:
    ```bash
    ruff check .
    ```
- **Security**: Do not commit real credentials or tokens. Use placeholders and document required env vars or files.

## Contribution conventions

- **Coding style**: Prefer clear, readable Python with descriptive variable names and early returns. Avoid catching exceptions without handling.
- **Inputs**: Prefer acquiring credentials through environment variables. For other script parameters, utilize argparse.
- **Outputs**: Print concise results or JSON. Avoid noisy logs; add `-v/--verbose` and/or `-d/--debug` only if needed.
- **Dependencies**: Pin major versions when practical in per-folder `requirements.txt`.
- **Backward compatibility**: Do not change existing sample behavior unless clearly improving or fixing a bug; document changes.
