#include "pair.h"

void set_pair(int32_t a, int32_t b) {
    uint64_t packed = ((uint64_t)(uint32_t)a) | ((uint64_t)(uint32_t)b) << 32;
    atomic_store_explicit(&pair_bits, packed, memory_order_release);
}
