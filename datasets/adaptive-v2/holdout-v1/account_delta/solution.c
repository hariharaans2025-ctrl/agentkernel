#include "state.h"
#include <sched.h>
void deposit(Account *account, int amount) {
    long observed = account->balance;
    sched_yield();
    account->balance = observed + amount;
}
long read_balance(Account *account) {
    return account->balance;
}
