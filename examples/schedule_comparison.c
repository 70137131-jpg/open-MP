/* Static scheduling hands out equal chunks up front; dynamic hands out work
   as threads finish. With uneven iterations, dynamic wins. */
#include <stdio.h>
#include <omp.h>

#define N 40

static double busy_work(int i) {
    double acc = 0.0;
    /* Later iterations cost more - a deliberately unbalanced workload. */
    for (long k = 0; k < (long)i * 200000L; k++) {
        acc += k % 7;
    }
    return acc;
}

int main(void) {
    double sink = 0.0;

    double start = omp_get_wtime();
    #pragma omp parallel for schedule(static) reduction(+:sink)
    for (int i = 0; i < N; i++) {
        sink += busy_work(i);
    }
    double static_time = omp_get_wtime() - start;

    start = omp_get_wtime();
    #pragma omp parallel for schedule(dynamic, 1) reduction(+:sink)
    for (int i = 0; i < N; i++) {
        sink += busy_work(i);
    }
    double dynamic_time = omp_get_wtime() - start;

    printf("schedule(static):     %.3f s\n", static_time);
    printf("schedule(dynamic, 1): %.3f s\n", dynamic_time);
    printf("speedup from dynamic: %.2fx\n", static_time / dynamic_time);
    return 0;
}
