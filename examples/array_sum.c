/* reduction(+:sum) gives each thread a private accumulator and combines them
   at the end of the loop - no locking, no race. */
#include <stdio.h>
#include <omp.h>

#define N 1000

int main(void) {
    int arr[N];
    long sum = 0;

    for (int i = 0; i < N; i++) {
        arr[i] = i + 1;
    }

    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < N; i++) {
        sum += arr[i];
    }

    printf("Sum of 1..%d = %ld\n", N, sum);
    printf("Expected:     %d\n", (N * (N + 1)) / 2);
    return 0;
}
