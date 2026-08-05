// Reductions work the same over a std::vector, as long as the loop counter is
// a signed integer type that OpenMP can canonicalise.
#include <iostream>
#include <numeric>
#include <vector>
#include <omp.h>

int main() {
    constexpr int n = 1000;
    std::vector<int> values(n);
    std::iota(values.begin(), values.end(), 1);

    long long sum = 0;
    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < n; ++i) {
        sum += values[i];
    }

    std::cout << "Sum of 1.." << n << " = " << sum << '\n';
    std::cout << "Expected:      " << static_cast<long long>(n) * (n + 1) / 2 << '\n';
    return 0;
}
