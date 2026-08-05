/* The smallest useful OpenMP program: every thread announces itself. */
#include <stdio.h>
#include <omp.h>

int main(void) {
    #pragma omp parallel
    {
        int thread_id = omp_get_thread_num();
        int total_threads = omp_get_num_threads();
        printf("Hello from thread %d of %d\n", thread_id, total_threads);
    }
    return 0;
}
