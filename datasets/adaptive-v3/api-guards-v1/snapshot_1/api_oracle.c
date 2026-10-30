#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);publish(&s,17);ok &= s.tag==17 && s.checksum==(17^0x65) && check_snapshot(&s);s.checksum^=1;ok &= !check_snapshot(&s);s.checksum^=1;publish(&s,23);ok &= s.tag==23 && s.checksum==(23^0x65) && check_snapshot(&s);if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
