#include "state.h"
static void credit(int to) {
    pthread_mutex_lock(&ledger);
    accounts[to] += 1;
    pthread_mutex_unlock(&ledger);
}
void transfer(int from, int to) {
    pthread_mutex_lock(&ledger);
    accounts[from] -= 1;
    credit(to);
    pthread_mutex_unlock(&ledger);
}
