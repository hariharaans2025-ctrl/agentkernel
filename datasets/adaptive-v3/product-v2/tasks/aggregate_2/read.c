#include "state.h"
int consistent(State*s){int t=s->total,a=s->accepted,r=s->rejected;return t==a+r;}
