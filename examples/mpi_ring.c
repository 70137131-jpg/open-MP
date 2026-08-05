/* Pass a token around the ring: rank 0 starts it, each rank increments and
   forwards it, rank 0 receives it back from the last rank. */
#include <mpi.h>
#include <stdio.h>

int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);

    int rank = 0, size = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    if (size < 2) {
        if (rank == 0) {
            printf("This example needs at least 2 processes.\n");
        }
        MPI_Finalize();
        return 0;
    }

    int token = 0;
    int next = (rank + 1) % size;
    int prev = (rank - 1 + size) % size;

    if (rank == 0) {
        token = 1;
        MPI_Send(&token, 1, MPI_INT, next, 0, MPI_COMM_WORLD);
        MPI_Recv(&token, 1, MPI_INT, prev, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        printf("Rank 0 got the token back with value %d after %d hops\n", token, size);
    } else {
        MPI_Recv(&token, 1, MPI_INT, prev, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        printf("Rank %d received %d from rank %d\n", rank, token, prev);
        token++;
        MPI_Send(&token, 1, MPI_INT, next, 0, MPI_COMM_WORLD);
    }

    MPI_Finalize();
    return 0;
}
