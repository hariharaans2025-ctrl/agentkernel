#include "state.h"
#include <sched.h>
int reserve_ticket(TicketOffice *office) {
    int ticket = office->next_ticket;
    sched_yield();
    office->next_ticket = ticket + 1;
    return ticket;
}
int issued_count(TicketOffice *office) {
    return office->next_ticket;
}
