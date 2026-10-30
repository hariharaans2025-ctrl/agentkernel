#include "state.h"
int consistent(State*s){int a=s->parity[0],b=s->parity[1],t=s->total;return a+b==t;}
