#include "state.h"
#include <sched.h>
int reserve_ticket(TicketOffice *office) {
    pthread_mutex_lock(&office->mutex);
    int ticket = office->next_ticket;
    sched_yield();
    office->next_ticket = ticket + 1;
    pthread_mutex_unlock(&office->mutex);
    return ticket;
}
int issued_count(TicketOffice *office) {
    pthread_mutex_lock(&office->mutex);
    int result = office->next_ticket;
    pthread_mutex_unlock(&office->mutex);
    return result;
}
