/* AUTO-GENERATED - do not edit.
 * Source: examples/manifest.json + examples/*.c|cpp
 * Regenerate: python3 scripts/build_examples.py
 */
window.OPENMP_EXAMPLES = [
  {
    "id": "hello_world",
    "title": "Hello World",
    "language": "c",
    "mode": "openmp",
    "description": "Every thread in a parallel region prints its own id.",
    "source": "/* The smallest useful OpenMP program: every thread announces itself. */\n#include <stdio.h>\n#include <omp.h>\n\nint main(void) {\n    #pragma omp parallel\n    {\n        int thread_id = omp_get_thread_num();\n        int total_threads = omp_get_num_threads();\n        printf(\"Hello from thread %d of %d\\n\", thread_id, total_threads);\n    }\n    return 0;\n}"
  },
  {
    "id": "array_sum",
    "title": "Array Sum",
    "language": "c",
    "mode": "openmp",
    "description": "Summing an array with reduction(+:sum) instead of a lock.",
    "source": "/* reduction(+:sum) gives each thread a private accumulator and combines them\n   at the end of the loop - no locking, no race. */\n#include <stdio.h>\n#include <omp.h>\n\n#define N 1000\n\nint main(void) {\n    int arr[N];\n    long sum = 0;\n\n    for (int i = 0; i < N; i++) {\n        arr[i] = i + 1;\n    }\n\n    #pragma omp parallel for reduction(+:sum)\n    for (int i = 0; i < N; i++) {\n        sum += arr[i];\n    }\n\n    printf(\"Sum of 1..%d = %ld\\n\", N, sum);\n    printf(\"Expected:     %d\\n\", (N * (N + 1)) / 2);\n    return 0;\n}"
  },
  {
    "id": "private_vs_shared",
    "title": "Private vs Shared",
    "language": "c",
    "mode": "openmp",
    "description": "What the private and shared data-sharing clauses actually do.",
    "source": "/* private(x) gives every thread its own uninitialised copy; shared(x) means\n   one variable for all threads, so writes to it need synchronising. */\n#include <stdio.h>\n#include <omp.h>\n\nint main(void) {\n    int shared_var = 0;\n    int private_var = 100;\n\n    printf(\"Before parallel region:\\n\");\n    printf(\"shared_var = %d, private_var = %d\\n\\n\", shared_var, private_var);\n\n    #pragma omp parallel num_threads(4) private(private_var) shared(shared_var)\n    {\n        int tid = omp_get_thread_num();\n        private_var = tid * 10;\n\n        #pragma omp critical\n        {\n            shared_var += tid;\n            printf(\"Thread %d: private_var = %d, shared_var = %d\\n\",\n                   tid, private_var, shared_var);\n        }\n    }\n\n    printf(\"\\nAfter parallel region:\\n\");\n    printf(\"shared_var = %d, private_var = %d\\n\", shared_var, private_var);\n    printf(\"(private_var is unchanged: the threads wrote to their own copies)\\n\");\n    return 0;\n}"
  },
  {
    "id": "critical_section",
    "title": "Critical Section",
    "language": "c",
    "mode": "openmp",
    "description": "The same counter loop with and without a data race.",
    "source": "/* The same loop run twice: once with a data race, once serialised by\n   #pragma omp critical. Run it a few times - the racy total varies. */\n#include <stdio.h>\n#include <omp.h>\n\n#define ITERATIONS 100000\n\nint main(void) {\n    int counter = 0;\n\n    #pragma omp parallel for num_threads(4)\n    for (int i = 0; i < ITERATIONS; i++) {\n        counter++;  /* race: read-modify-write is not atomic */\n    }\n    printf(\"Without critical: %d (expected %d)\\n\", counter, ITERATIONS);\n\n    counter = 0;\n    #pragma omp parallel for num_threads(4)\n    for (int i = 0; i < ITERATIONS; i++) {\n        #pragma omp critical\n        counter++;\n    }\n    printf(\"With critical:    %d (expected %d)\\n\", counter, ITERATIONS);\n    return 0;\n}"
  },
  {
    "id": "schedule_comparison",
    "title": "Static vs Dynamic",
    "language": "c",
    "mode": "openmp",
    "description": "Timing an unbalanced loop under static and dynamic scheduling.",
    "source": "/* Static scheduling hands out equal chunks up front; dynamic hands out work\n   as threads finish. With uneven iterations, dynamic wins. */\n#include <stdio.h>\n#include <omp.h>\n\n#define N 40\n\nstatic double busy_work(int i) {\n    double acc = 0.0;\n    /* Later iterations cost more - a deliberately unbalanced workload. */\n    for (long k = 0; k < (long)i * 200000L; k++) {\n        acc += k % 7;\n    }\n    return acc;\n}\n\nint main(void) {\n    double sink = 0.0;\n\n    double start = omp_get_wtime();\n    #pragma omp parallel for schedule(static) reduction(+:sink)\n    for (int i = 0; i < N; i++) {\n        sink += busy_work(i);\n    }\n    double static_time = omp_get_wtime() - start;\n\n    start = omp_get_wtime();\n    #pragma omp parallel for schedule(dynamic, 1) reduction(+:sink)\n    for (int i = 0; i < N; i++) {\n        sink += busy_work(i);\n    }\n    double dynamic_time = omp_get_wtime() - start;\n\n    printf(\"schedule(static):     %.3f s\\n\", static_time);\n    printf(\"schedule(dynamic, 1): %.3f s\\n\", dynamic_time);\n    printf(\"speedup from dynamic: %.2fx\\n\", static_time / dynamic_time);\n    return 0;\n}"
  },
  {
    "id": "mpi_hello",
    "title": "MPI Hello",
    "language": "c",
    "mode": "mpi",
    "description": "Rank and communicator size from MPI_COMM_WORLD.",
    "source": "/* Every rank is a separate process with its own memory. */\n#include <mpi.h>\n#include <stdio.h>\n\nint main(int argc, char **argv) {\n    MPI_Init(&argc, &argv);\n\n    int rank = 0, size = 0;\n    MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n    MPI_Comm_size(MPI_COMM_WORLD, &size);\n\n    printf(\"Hello from rank %d of %d\\n\", rank, size);\n\n    MPI_Finalize();\n    return 0;\n}"
  },
  {
    "id": "mpi_ring",
    "title": "MPI Token Ring",
    "language": "c",
    "mode": "mpi",
    "description": "Blocking MPI_Send / MPI_Recv passing a token around a ring.",
    "source": "/* Pass a token around the ring: rank 0 starts it, each rank increments and\n   forwards it, rank 0 receives it back from the last rank. */\n#include <mpi.h>\n#include <stdio.h>\n\nint main(int argc, char **argv) {\n    MPI_Init(&argc, &argv);\n\n    int rank = 0, size = 0;\n    MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n    MPI_Comm_size(MPI_COMM_WORLD, &size);\n\n    if (size < 2) {\n        if (rank == 0) {\n            printf(\"This example needs at least 2 processes.\\n\");\n        }\n        MPI_Finalize();\n        return 0;\n    }\n\n    int token = 0;\n    int next = (rank + 1) % size;\n    int prev = (rank - 1 + size) % size;\n\n    if (rank == 0) {\n        token = 1;\n        MPI_Send(&token, 1, MPI_INT, next, 0, MPI_COMM_WORLD);\n        MPI_Recv(&token, 1, MPI_INT, prev, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);\n        printf(\"Rank 0 got the token back with value %d after %d hops\\n\", token, size);\n    } else {\n        MPI_Recv(&token, 1, MPI_INT, prev, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);\n        printf(\"Rank %d received %d from rank %d\\n\", rank, token, prev);\n        token++;\n        MPI_Send(&token, 1, MPI_INT, next, 0, MPI_COMM_WORLD);\n    }\n\n    MPI_Finalize();\n    return 0;\n}"
  },
  {
    "id": "cpp_hello",
    "title": "C++ Hello",
    "language": "cpp",
    "mode": "openmp",
    "description": "Keeping std::cout output intact across threads.",
    "source": "// std::cout is thread safe but interleaves freely, so the critical section is\n// what keeps each line intact.\n#include <iostream>\n#include <omp.h>\n\nint main() {\n    #pragma omp parallel\n    {\n        int thread_id = omp_get_thread_num();\n        int total_threads = omp_get_num_threads();\n\n        #pragma omp critical\n        std::cout << \"Hello from thread \" << thread_id\n                  << \" of \" << total_threads << '\\n';\n    }\n    return 0;\n}"
  },
  {
    "id": "cpp_vector",
    "title": "C++ Vector Sum",
    "language": "cpp",
    "mode": "openmp",
    "description": "A reduction over std::vector.",
    "source": "// Reductions work the same over a std::vector, as long as the loop counter is\n// a signed integer type that OpenMP can canonicalise.\n#include <iostream>\n#include <numeric>\n#include <vector>\n#include <omp.h>\n\nint main() {\n    constexpr int n = 1000;\n    std::vector<int> values(n);\n    std::iota(values.begin(), values.end(), 1);\n\n    long long sum = 0;\n    #pragma omp parallel for reduction(+:sum)\n    for (int i = 0; i < n; ++i) {\n        sum += values[i];\n    }\n\n    std::cout << \"Sum of 1..\" << n << \" = \" << sum << '\\n';\n    std::cout << \"Expected:      \" << static_cast<long long>(n) * (n + 1) / 2 << '\\n';\n    return 0;\n}"
  },
  {
    "id": "mpi_cpp_hello",
    "title": "MPI C++ Hello",
    "language": "cpp",
    "mode": "mpi",
    "description": "Calling the MPI C API from C++.",
    "source": "// The C++ bindings were removed in MPI-3; use the C API from C++.\n#include <mpi.h>\n#include <iostream>\n\nint main(int argc, char **argv) {\n    MPI_Init(&argc, &argv);\n\n    int rank = 0, size = 0;\n    MPI_Comm_rank(MPI_COMM_WORLD, &rank);\n    MPI_Comm_size(MPI_COMM_WORLD, &size);\n\n    std::cout << \"Hello from rank \" << rank << \" of \" << size << '\\n';\n\n    MPI_Finalize();\n    return 0;\n}"
  }
];
