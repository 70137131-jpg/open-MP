/* The same loop run twice: once with a data race, once serialised by
   #pragma omp critical. Run it a few times - the racy total varies. */
#include <stdio.h>
#include <omp.h>

#define ITERATIONS 100000

int main(void) {
    int counter = 0;

    #pragma omp parallel for num_threads(4)
    for (int i = 0; i < ITERATIONS; i++) {
        counter++;  /* race: read-modify-write is not atomic */
    }
    printf("Without critical: %d (expected %d)\n", counter, ITERATIONS);

    counter = 0;
    #pragma omp parallel for num_threads(4)
    for (int i = 0; i < ITERATIONS; i++) {
        #pragma omp critical
        counter++;
    }
    printf("With critical:    %d (expected %d)\n", counter, ITERATIONS);
    return 0;
}
