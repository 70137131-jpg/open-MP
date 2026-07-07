# OpenMP Online Compiler 🔧

A web-based compiler for OpenMP programs with a beautiful code editor interface.

**Live demo:** [open-mp-theta.vercel.app](https://open-mp-theta.vercel.app/)

## Features ✨

- 🎨 Beautiful, modern UI with syntax highlighting
- 🚀 Real-time OpenMP code compilation and execution
- 🧵 Adjustable thread count (1-16 threads)
- 📚 Pre-loaded example programs
- 🎯 Error highlighting and detailed output
- ⌨️ Keyboard shortcuts (Ctrl/Cmd + Enter to run)
- 📱 Responsive design
- 🧩 MPI support (single-node)
- ➕ C++ support (OpenMP and MPI modes)

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Frontend      │  HTTP   │   Flask API     │
│  (HTML/JS)      │◄───────►│   (Python)      │
│  - CodeMirror   │         │   - Compile     │
│  - Monaco Theme │         │   - Execute     │
└─────────────────┘         └─────────────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  GCC + OpenMP   │
                            │  Compiler       │
                            └─────────────────┘
```

## Prerequisites 📋

### Required
- Python 3.8 or higher
- GCC compiler with OpenMP support
- pip (Python package manager)

### Optional (for production)
- Docker (recommended for security)
- nginx (for reverse proxy)

## Installation Guide 🚀

### Method 1: Direct Installation (Development)

#### Step 1: Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y gcc python3 python3-pip
```

**macOS:**
```bash
brew install gcc python3
```

**Windows:**
- Install MinGW-w64 with GCC
- Install Python from python.org
- Add both to PATH

#### Step 2: Verify OpenMP Support
```bash
gcc --version
echo '#include <omp.h>
int main() { return 0; }' | gcc -fopenmp -xc - -o test && ./test
```

#### Step 3: Clone/Download the Project
```bash
mkdir openmp-compiler
cd openmp-compiler

# Copy all files:
# - app.py
# - index.html
# - requirements.txt
```

#### Step 4: Install Python Dependencies
```bash
pip install -r requirements.txt
```

#### Step 5: Run the Backend
```bash
python app.py
```
The backend will start on `http://localhost:5000`

#### Step 6: Open the Frontend
Open `index.html` directly in your browser, or serve it with:
```bash
python -m http.server 8000
# Then open: http://localhost:8000
```

---

### Method 2: Docker Installation (Production - RECOMMENDED)

Docker provides isolation and security for running untrusted code.

#### Step 1: Create Dockerfile

```dockerfile
FROM gcc:latest

# Install Python
RUN apt-get update && apt-get install -y python3 python3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

CMD ["python3", "app.py"]
```

#### Step 2: Create docker-compose.yml

```yaml
version: '3.8'

services:
  backend:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./app.py:/app/app.py
    environment:
      - FLASK_ENV=production
    restart: unless-stopped

  frontend:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./index.html:/usr/share/nginx/html/index.html:ro
    restart: unless-stopped
```

#### Step 3: Run with Docker
```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Access the application at `http://localhost:8080`

---

## Security Considerations ⚠️

### Current Implementation (Development Only)
Suitable for:
- ✅ Learning and education
- ✅ Personal use
- ✅ Controlled environments

**NOT suitable for:**
- ❌ Public-facing production
- ❌ Untrusted user input
- ❌ Multi-tenant systems

### Security Risks
1. **Code Execution** — users can run arbitrary C/C++ code
2. **Resource Exhaustion** — infinite loops, memory leaks
3. **File System Access** — programs can read/write files
4. **Network Access** — programs can make network calls

### Hardening for Production

#### 1. Use Docker with Security Limits
```yaml
services:
  backend:
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
```

#### 2. Add User Authentication
```bash
pip install flask-login flask-bcrypt
```

#### 3. Implement Rate Limiting
```bash
pip install flask-limiter
```

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10 per minute"]
)
```

#### 4. Use Sandboxing
- **gVisor** — container runtime sandbox
- **Firejail** — Linux namespace sandbox
- **seccomp** — syscall filtering

#### 5. Code Analysis Before Execution
```python
BLACKLIST = [
    'system(',
    'exec(',
    'fork(',
    'socket(',
    'open(',
    'fopen(',
    '__asm__'
]

def is_code_safe(code):
    for pattern in BLACKLIST:
        if pattern in code:
            return False, f"Dangerous pattern detected: {pattern}"
    return True, "OK"
```

---

## Usage Guide 📖

### Basic Workflow
1. **Write Code** — use the code editor (left panel)
2. **Select Language/Mode** — C or C++, OpenMP or MPI
3. **Select Threads/Processes** — choose thread or process count (1-16)
4. **Run** — click "Run Code" or press Ctrl+Enter
5. **View Output** — see results in the output panel (right)

### Keyboard Shortcuts
- `Ctrl/Cmd + Enter`: Run code
- `Tab`: Indent
- `Ctrl/Cmd + /`: Comment line

### Example Programs Available
1. **Hello World** — basic parallel region
2. **Array Sum** — reduction clause demo
3. **Private vs Shared** — variable scoping
4. **Critical Section** — race condition prevention

### MPI Support
Basic MPI C/C++ programs are supported, single-node only.

- **Requirements:** OpenMPI runtime (`mpicc`, `mpirun`)
- Select "MPI" in the UI and choose the process count.
- The backend compiles with `mpicc` and runs `mpirun -np <N>`.
- Single-node only; no multi-host clusters.
- Keep process counts low to avoid resource exhaustion.

### C++ Support
Compile and run C++ programs in both OpenMP and MPI modes.

- Select "C++" in the Language dropdown.
- Write standard C++ (C++11+ recommended).
- The backend uses `g++` for OpenMP and `mpicxx` for MPI.
- If a C example fails in C++, switch the language back to C.

---

## Troubleshooting 🔧

### Backend won't start
```bash
# Check if port 5000 is in use
lsof -i :5000          # Linux/Mac
netstat -ano | findstr :5000   # Windows

# Kill the process if needed
kill -9 <PID>
```

### GCC not found
```bash
which gcc
gcc --version

# Install if missing (Ubuntu)
sudo apt install gcc
```

### OpenMP not working
```bash
echo 'int main() {}' | gcc -fopenmp -xc - -o test

# If it fails, reinstall GCC
sudo apt install --reinstall gcc
```

### CORS errors
- Make sure Flask-CORS is installed
- Check the browser console for details
- Ensure `API_URL` in `index.html` matches the backend URL

### Compilation timeout
- Reduce thread/process count
- Simplify code
- Check for infinite loops

---

## API Documentation 📚

### POST `/compile`
Compile and execute OpenMP/MPI code.

**Request:**
```json
{
  "code": "#include <stdio.h>\n...",
  "threads": 4
}
```

**Response (Success):**
```json
{
  "success": true,
  "output": "Hello from thread 0...",
  "stderr": "",
  "returncode": 0
}
```

**Response (Error):**
```json
{
  "success": false,
  "error": "Compilation Error",
  "stderr": "program.c:5:2: error: ..."
}
```

### GET `/examples`
Get example programs.

**Response:**
```json
{
  "hello_world": "#include <stdio.h>...",
  "array_sum": "..."
}
```

### GET `/health`
Check backend status.

**Response:**
```json
{
  "status": "ok",
  "gcc_available": true,
  "gcc_version": "gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0"
}
```

---

## Customization 🎨

### Change Theme
Edit `index.html`:
```javascript
const editor = CodeMirror.fromTextArea(..., {
    theme: 'monokai',  // Try: dracula, material, solarized
    ...
});
```

### Add More Examples
Edit `app.py`:
```python
examples = {
    'my_example': '''#include <stdio.h>
// Your code here
'''
}
```

### Modify Timeout Limits
Edit `app.py`:
```python
# Compilation timeout
compile_result = subprocess.run(..., timeout=10)  # seconds

# Execution timeout
run_result = subprocess.run(..., timeout=5)  # seconds
```

---

## Deployment Options 🌐

### Option 1: Local Network
```bash
# Run backend on all interfaces
python app.py

# Access from other devices:
# http://<your-ip>:5000
```

### Option 2: Cloud Deployment (Heroku)
```bash
echo "web: python app.py" > Procfile

heroku create openmp-compiler
git push heroku main
```

### Option 3: VPS Deployment
```bash
# 1. Set up nginx reverse proxy
# 2. Use gunicorn for production
pip install gunicorn

# 3. Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Performance Tips 🚀

1. **Limit Thread Count** — don't allow more threads than CPU cores
2. **Set Resource Limits** — use ulimit or Docker limits
3. **Cache Compiled Binaries** — for repeated executions
4. **Use Async** — switch to async Flask for better concurrency

---

## FAQ ❓

**Q: Can I use this for production?**
A: Not as-is. Implement proper security (Docker, sandboxing, auth) first.

**Q: What's the maximum execution time?**
A: Default is 5 seconds. Modify the timeout in `app.py`.

**Q: Can I compile other languages?**
A: Currently C and C++ are supported. Fortran support could be added.

**Q: How do I debug my code?**
A: Add printf statements. Future versions may include GDB integration.

**Q: Can I save my code?**
A: Currently no. Add localStorage or database support.

---

## Resources

- **Live demo:** [open-mp-theta.vercel.app](https://open-mp-theta.vercel.app/)

---

## Contributing 🤝

Contributions are welcome! Areas for improvement:
- Better error messages
- More example programs
- Fortran support
- Interactive debugging
- Performance profiling
- Code autocomplete

---

## Credits 🙏

- **CodeMirror** — code editor
- **Flask** — backend framework
- **GCC** — compiler with OpenMP support

---

## License 📄

This project is open source and available under the MIT License.

---

Made with ❤️ for the OpenMP community
