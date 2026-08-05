// std::cout is thread safe but interleaves freely, so the critical section is
// what keeps each line intact.
#include <iostream>
#include <omp.h>

int main() {
    #pragma omp parallel
    {
        int thread_id = omp_get_thread_num();
        int total_threads = omp_get_num_threads();

        #pragma omp critical
        std::cout << "Hello from thread " << thread_id
                  << " of " << total_threads << '\n';
    }
    return 0;
}
