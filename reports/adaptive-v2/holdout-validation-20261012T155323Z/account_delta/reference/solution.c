#include "state.h"
#include <sched.h>
void deposit(Account *account, int amount) {
    pthread_mutex_lock(&account->mutex);
    long observed = account->balance;
    sched_yield();
    account->balance = observed + amount;
    pthread_mutex_unlock(&account->mutex);
}
long read_balance(Account *account) {
    pthread_mutex_lock(&account->mutex);
    long value = account->balance;
    pthread_mutex_unlock(&account->mutex);
    return value;
}
