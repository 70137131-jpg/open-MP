from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import subprocess
import os
import uuid
import tempfile
import shutil
from pathlib import Path

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Create temporary directory for code compilation
TEMP_DIR = Path(tempfile.gettempdir()) / "openmp_compiler"
TEMP_DIR.mkdir(exist_ok=True)
MAX_WORKERS = 16
VALID_MODES = {"openmp", "mpi"}
VALID_LANGS = {"c", "cpp"}

def cleanup_old_files():
    """Clean up files older than 1 hour"""
    import time
    current_time = time.time()
    for item in TEMP_DIR.iterdir():
        if item.is_file() or item.is_dir():
            if current_time - item.stat().st_mtime > 3600:  # 1 hour
                try:
                    if item.is_file():
                        item.unlink()
                    else:
                        shutil.rmtree(item)
                except:
                    pass

@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route('/compile', methods=['POST'])
def compile_code():
    try:
        data = request.get_json(silent=True) or {}
        code = data.get('code', '')
        mode = data.get('mode', 'openmp')
        language = data.get('language', 'c')

        try:
            worker_count = int(data.get('threads', 4))
        except (TypeError, ValueError):
            worker_count = 4
        worker_count = max(1, min(worker_count, MAX_WORKERS))
        
        if not code:
            return jsonify({'error': 'No code provided'}), 400
        if mode not in VALID_MODES:
            return jsonify({'error': 'Invalid mode. Use "openmp" or "mpi".'}), 400
        if language not in VALID_LANGS:
            return jsonify({'error': 'Invalid language. Use "c" or "cpp".'}), 400
        
        # Generate unique ID for this compilation
        job_id = str(uuid.uuid4())
        job_dir = TEMP_DIR / job_id
        job_dir.mkdir()
        
        # Write code to file
        source_file = job_dir / ("program.cpp" if language == "cpp" else "program.c")
        executable = job_dir / "program"
        
        with open(source_file, 'w') as f:
            f.write(code)
        
        # Compile
        if mode == 'mpi':
            compiler = 'mpicxx' if language == 'cpp' else 'mpicc'
            compile_cmd = [
                compiler,
                str(source_file),
                '-o',
                str(executable),
                '-lm'  # Link math library
            ]
        else:
            compiler = 'g++' if language == 'cpp' else 'gcc'
            compile_cmd = [
                compiler,
                '-fopenmp',
                str(source_file),
                '-o',
                str(executable),
                '-lm'  # Link math library
            ]
        
        compile_result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if compile_result.returncode != 0:
            # Compilation failed
            shutil.rmtree(job_dir)
            return jsonify({
                'success': False,
                'error': 'Compilation Error',
                'stderr': compile_result.stderr,
                'stdout': compile_result.stdout
            })
        
        # Run the compiled program
        env = os.environ.copy()
        if mode == 'mpi':
            env['OMPI_ALLOW_RUN_AS_ROOT'] = '1'
            env['OMPI_ALLOW_RUN_AS_ROOT_CONFIRM'] = '1'
            run_cmd = [
                'mpirun',
                '--allow-run-as-root',
                '--oversubscribe',
                '-np',
                str(worker_count),
                str(executable)
            ]
        else:
            env['OMP_NUM_THREADS'] = str(worker_count)
            run_cmd = [str(executable)]
        
        run_result = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )
        
        # Clean up
        shutil.rmtree(job_dir)
        cleanup_old_files()
        
        return jsonify({
            'success': True,
            'output': run_result.stdout,
            'stderr': run_result.stderr,
            'returncode': run_result.returncode
        })
        
    except subprocess.TimeoutExpired:
        if 'job_dir' in locals():
            shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({
            'success': False,
            'error': 'Timeout',
            'stderr': 'Program execution took too long (>5 seconds)'
        }), 408
        
    except Exception as e:
        if 'job_dir' in locals():
            shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({
            'success': False,
            'error': 'Internal Server Error',
            'stderr': str(e)
        }), 500

@app.route('/examples', methods=['GET'])
def get_examples():
    """Return example OpenMP programs"""
    examples = {
        'hello_world': '''#include <stdio.h>
#include <omp.h>

int main() {
    #pragma omp parallel
    {
        int thread_id = omp_get_thread_num();
        int total_threads = omp_get_num_threads();
        printf("Hello from thread %d of %d\\n", thread_id, total_threads);
    }
    return 0;
}''',
        'array_sum': '''#include <stdio.h>
#include <omp.h>

int main() {
    int n = 1000;
    int arr[1000];
    int sum = 0;
    
    // Initialize array
    for (int i = 0; i < n; i++) {
        arr[i] = i + 1;
    }
    
    // Parallel sum using reduction
    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < n; i++) {
        sum += arr[i];
    }
    
    printf("Sum of 1 to %d = %d\\n", n, sum);
    printf("Expected: %d\\n", (n * (n + 1)) / 2);
    return 0;
}''',
        'private_vs_shared': '''#include <stdio.h>
#include <omp.h>

int main() {
    int shared_var = 0;
    int private_var = 100;
    
    printf("Before parallel region:\\n");
    printf("shared_var = %d, private_var = %d\\n\\n", shared_var, private_var);
    
    #pragma omp parallel num_threads(4) private(private_var) shared(shared_var)
    {
        int tid = omp_get_thread_num();
        private_var = tid * 10;  // Each thread has its own copy
        
        #pragma omp critical
        {
            shared_var += tid;  // All threads share this variable
            printf("Thread %d: private_var = %d, shared_var = %d\\n", 
                   tid, private_var, shared_var);
        }
    }
    
    printf("\\nAfter parallel region:\\n");
    printf("shared_var = %d, private_var = %d\\n", shared_var, private_var);
    return 0;
}''',
        'critical_section': '''#include <stdio.h>
#include <omp.h>

int main() {
    int counter = 0;
    
    printf("Without critical section (race condition):\\n");
    #pragma omp parallel for num_threads(4)
    for (int i = 0; i < 1000; i++) {
        counter++;  // Race condition!
    }
    printf("Counter = %d (should be 1000)\\n\\n", counter);
    
    counter = 0;
    printf("With critical section:\\n");
    #pragma omp parallel for num_threads(4)
    for (int i = 0; i < 1000; i++) {
        #pragma omp critical
        counter++;
    }
    printf("Counter = %d (correct!)\\n", counter);
    return 0;
}''',
        'mpi_hello': '''#include <mpi.h>
#include <stdio.h>

int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);
    int rank = 0;
    int size = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    printf("Hello from rank %d of %d\\n", rank, size);
    MPI_Finalize();
    return 0;
}'''
    }
    return jsonify(examples)

@app.route('/health', methods=['GET'])
def health_check():
    """Check if OpenMP is available"""
    try:
        result = subprocess.run(
            ['gcc', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        mpi_result = subprocess.run(
            ['mpicc', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        gpp_result = subprocess.run(
            ['g++', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        mpicxx_result = subprocess.run(
            ['mpicxx', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return jsonify({
            'status': 'ok',
            'gcc_available': result.returncode == 0,
            'gcc_version': result.stdout.split('\n')[0] if result.returncode == 0 else None,
            'mpi_available': mpi_result.returncode == 0,
            'mpi_version': mpi_result.stdout.split('\n')[0] if mpi_result.returncode == 0 else None,
            'gpp_available': gpp_result.returncode == 0,
            'gpp_version': gpp_result.stdout.split('\n')[0] if gpp_result.returncode == 0 else None,
            'mpicxx_available': mpicxx_result.returncode == 0,
            'mpicxx_version': mpicxx_result.stdout.split('\n')[0] if mpicxx_result.returncode == 0 else None
        })
    except Exception as e:
        return jsonify({
            'status': 'ok', 
            'gcc_available': False,
            'error': 'GCC not found - please install MinGW-w64 or GCC'
        }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)

