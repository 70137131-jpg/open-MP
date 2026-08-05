/* private(x) gives every thread its own uninitialised copy; shared(x) means
   one variable for all threads, so writes to it need synchronising. */
#include <stdio.h>
#include <omp.h>

int main(void) {
    int shared_var = 0;
    int private_var = 100;

    printf("Before parallel region:\n");
    printf("shared_var = %d, private_var = %d\n\n", shared_var, private_var);

    #pragma omp parallel num_threads(4) private(private_var) shared(shared_var)
    {
        int tid = omp_get_thread_num();
        private_var = tid * 10;

        #pragma omp critical
        {
            shared_var += tid;
            printf("Thread %d: private_var = %d, shared_var = %d\n",
                   tid, private_var, shared_var);
        }
    }

    printf("\nAfter parallel region:\n");
    printf("shared_var = %d, private_var = %d\n", shared_var, private_var);
    printf("(private_var is unchanged: the threads wrote to their own copies)\n");
    return 0;
}
