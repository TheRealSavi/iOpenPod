/* SPDX-License-Identifier: GPL-3.0-only
 * SPI/SST25 sequencing derived from Rockbox 10ec9bd5:
 * norboot-s5l8702.c and spi-s5l8702.c, Copyright (C) 2009 Michael Sparmann.
 * Qualification scope and limits are recorded in scripts/bootloader/README.md.
 */
#include <stdint.h>
#include <stddef.h>
#include "vendor/sha256.h"
#include "config.h"
#define REG(a) (*(volatile uint32_t *)(a))
#define SPI(a) REG(0x3c300000u+(a))
#define AES(a) REG(0x38c00000u+(a))
#define WORK ((uint8_t *)0x22020000u)
#define RECORD ((volatile struct record *)0x2201f000u)
#define FIFO_POLLS 100000u
#define BUSY_POLLS 250000u
#define AES_POLLS 10000000u
struct record {
 uint32_t magic,version,phase; int32_t error;
 uint32_t sector_size,bytes,reserved0,reserved1;
 uint8_t nonce[16]; uint32_t returns,reserved[3];
 uint32_t jedec,mode,verified_blocks,error_block,write_commands;
 uint8_t before_hash[32],target_hash[32],after_hash[32],outside_hash[32];
};
extern const uint8_t packed_header[80],packed_body[PACKED_BYTES],return_blob[];
extern const uint32_t return_blob_size;
static uint8_t scratch[4096];
static int io_error;
static uint32_t old_gpio,old_power,old_spi[6];
static uint8_t initial_status;
void *memcpy(void *d,const void *s,size_t n) {uint8_t *x=d;const uint8_t*y=s;while(n--)*x++=*y++;return d;}
void *memset(void*d,int v,size_t n) {uint8_t*x=d;while(n--)*x++=(uint8_t)v;return d;}
int memcmp(const void*a,const void*b,size_t n) {const uint8_t*x=a,*y=b;while(n--){if(*x!=*y)return *x-*y;x++;y++;}return 0;}
static void cs(int on) {REG(0x3cf00200)=on?0x0e:0x0f;}
static int xfer(uint8_t tx,uint8_t *rx) {
 if(io_error)return 0;
 SPI(0x34)=1;
 unsigned n=FIFO_POLLS;while((SPI(8)&0x1f0)==0x100 && --n){};
 if(!n){io_error=-10;return 0;}
 SPI(0x10)=tx;
 n=FIFO_POLLS;while(!(SPI(8)&0x3e00) && --n){};
 if(!n){io_error=-11;return 0;}
 *rx=(uint8_t)SPI(0x20);return 1;
}
static int put(uint8_t b){uint8_t v;return xfer(b,&v);}
static int status(uint8_t *v){cs(1);int ok=put(5)&&xfer(0xff,v);cs(0);return ok;}
static int wait_ready(void){for(unsigned n=0;n<BUSY_POLLS;n++){uint8_t v;if(!status(&v))return 0;if(!(v&1))return 1;}io_error=-12;return 0;}
static int read_nor(uint32_t at,uint8_t *out,uint32_t n){
 if(at>0x100000u || n>0x100000u-at)return 0;
 if(!wait_ready())return 0;
 cs(1);int ok=put(3)&&put(at>>16)&&put(at>>8)&&put(at);
 for(uint32_t i=0;ok&&i<n;i++)ok=xfer(0xff,out+i);
 cs(0);return ok;
}
static void spi_open(void){
 old_gpio=REG(0x3cf00000);old_power=REG(0x3c50004c);
 REG(0x3c50004c)=old_power&~((1u<<2)|(1u<<12));
 old_spi[0]=SPI(0);old_spi[1]=SPI(4);old_spi[2]=SPI(0xc);old_spi[3]=SPI(0x30);old_spi[4]=SPI(0x34);old_spi[5]=SPI(0x38);
 REG(0x3cf00000)=(old_gpio&~0xffffu)|0x2222;
 cs(0);SPI(8)=15;SPI(0)|=12;SPI(0x30)=4;SPI(0xc)=6;SPI(4)=0x10618;SPI(0)|=12;SPI(0)=1;
}
static void spi_close(void){cs(0);SPI(0)=old_spi[0];SPI(4)=old_spi[1];SPI(0xc)=old_spi[2];SPI(0x30)=old_spi[3];SPI(0x34)=old_spi[4];SPI(0x38)=old_spi[5];REG(0x3cf00000)=old_gpio;REG(0x3c50004c)=old_power;}
static int jedec(uint32_t *out){uint8_t a,b,c;cs(1);int ok=put(0x9f)&&xfer(0xff,&a)&&xfer(0xff,&b)&&xfer(0xff,&c);cs(0);if(ok)*out=((uint32_t)a<<16)|((uint32_t)b<<8)|c;return ok;}
static void digest(const void *p,uint32_t n,uint8_t out[32]){struct sha256 s;sha256_init(&s);sha256_update(&s,p,n);sha256_final(&s,out);}
static int scan(uint8_t full[32],uint8_t boot[32],uint8_t outside[32],uint8_t syscfg[32]){
 struct sha256 a,b,c,d;sha256_init(&a);sha256_init(&b);sha256_init(&c);sha256_init(&d);
 for(uint32_t at=0;at<0x100000;at+=sizeof(scratch)){
  if(!read_nor(at,scratch,sizeof(scratch)))return 0;
  sha256_update(&a,scratch,sizeof(scratch));
  if(at>=0x8000&&at<0x28000)sha256_update(&b,scratch,sizeof(scratch));else sha256_update(&c,scratch,sizeof(scratch));
  if(at<0x8000)sha256_update(&d,scratch,sizeof(scratch));
 }
 sha256_final(&a,full);sha256_final(&b,boot);sha256_final(&c,outside);sha256_final(&d,syscfg);return 1;
}
static int encrypt_original_body(void){
 uint32_t clock=REG(0x3c500048);REG(0x3c500048)=clock&~(1u<<10);
 for(unsigned i=0;i<4;i++)AES(0x74+4*i)=0;
 AES(8)=1;AES(8)=0;AES(0)=1;AES(0x10)=0;AES(0x6c)=2;AES(0x88)=~2u;AES(0x8c)=0;AES(0x14)=9;
 AES(0x18)=0x1f800;AES(0x20)=(uint32_t)(WORK+0x800);AES(0x24)=0x1f800;AES(0x28)=(uint32_t)(WORK+0x800);
 AES(0x2c)=0x1f800;AES(0x30)=(uint32_t)(WORK+0x800);AES(0x34)=0x1f800;AES(4)=1;
 unsigned n=AES_POLLS;while(!(AES(0xc)&15)&&--n){};
 REG(0x3c500048)=clock;return n!=0;
}
#if WRITE_ENABLED
static int command(uint8_t c){cs(1);int ok=put(c);cs(0);RECORD->write_commands++;return ok;}
static int write_status(uint8_t v){if(!wait_ready()||!command(0x50))return 0;cs(1);int ok=put(1)&&put(v);cs(0);RECORD->write_commands++;return ok&&wait_ready();}
static int write_enable(void){uint8_t s;return command(6)&&status(&s)&&(s&2);}
static int program_sector(uint32_t at,const uint8_t *data){
 if(at<0x8000||at>0x27000||(at&0xfff)){io_error=-20;return 0;}
 if(!wait_ready()||!write_enable())return 0;
 cs(1);int ok=put(0x20)&&put(at>>16)&&put(at>>8)&&put(at);cs(0);RECORD->write_commands++;
 if(!ok||!wait_ready()||!write_enable())return 0;
 for(unsigned i=0;i<4096;i+=2){
  cs(1);ok=put(0xad);
  if(!i)ok=ok&&put(at>>16)&&put(at>>8)&&put(at);
  ok=ok&&put(data[i])&&put(data[i+1]);cs(0);RECORD->write_commands++;
  if(!ok||!wait_ready())return 0;
 }
 return command(4)&&wait_ready();
}
#endif
int main_logic(void){
 uint8_t full[32],boot[32],outside[32],syscfg[32],target[32];uint32_t id=0;
 RECORD->phase=2;spi_open();
 if(!status(&initial_status)){spi_close();return -1;}
#if ROLLBACK && WRITE_ENABLED
 if((initial_status&0x40)&&(!wait_ready()||!command(4)||!wait_ready()||!status(&initial_status))){spi_close();return -30;}
#endif
 if(!jedec(&id)){spi_close();return -1;}
 RECORD->jedec=id;
 if(initial_status&0x40){spi_close();return -2;} /* Never unknowingly inherit AAI mode. */
 if(EXPECTED_JEDEC && id!=EXPECTED_JEDEC){spi_close();return -3;}
 if(!scan(full,boot,outside,syscfg)){spi_close();return -4;}
 memcpy((void*)RECORD->before_hash,full,32);memcpy((void*)RECORD->outside_hash,outside,32);
 if(memcmp(syscfg,expected_syscfg,32)||memcmp(outside,expected_outside,32)){spi_close();return -5;}
#if !ROLLBACK
 if(memcmp(full,expected_original_full,32)||memcmp(boot,expected_original_boot,32)){spi_close();return -6;}
#endif
 RECORD->phase=3;memset(WORK,0,0x800);memcpy(WORK,packed_header,80);
 memcpy(WORK+0x800,packed_body,GAP_START);memset(WORK+0x800+GAP_START,0xff,SECCORE_OFFSET-GAP_START);memcpy(WORK+0x800+SECCORE_OFFSET,packed_body+GAP_START,SECCORE_BYTES);
#if ROLLBACK && ROLLBACK_ENCRYPTED
 if(!encrypt_original_body()){spi_close();return -7;}
#endif
 digest(WORK,0x20000,target);memcpy((void*)RECORD->target_hash,target,32);
 if(memcmp(target,expected_target,32)){spi_close();return -8;}
 RECORD->phase=4;
#if WRITE_ENABLED
 if(!EXPECTED_JEDEC){spi_close();return -9;}
 uint8_t protection;
 if(!write_status(initial_status&0xa0)||!status(&protection)||(protection&0x1c)){spi_close();return -21;}
 /* Commit the IM3 header sector last. This reduces early header replacement,
  * but cannot make a multi-sector NOR update atomic or preserve bootability
  * after an interrupted body write. DFU rollback is still required. */
 for(uint32_t step=0;step<32;step++){
  uint32_t i=(step+1)&31u;
  uint32_t at=0x8000+i*4096;RECORD->error_block=i;
  if(!read_nor(at,scratch,4096)){spi_close();return -22;}
  if(memcmp(scratch,WORK+i*4096,4096)){
   if(!program_sector(at,WORK+i*4096)){spi_close();return -23;}
   if(!read_nor(at,scratch,4096)||memcmp(scratch,WORK+i*4096,4096)){spi_close();return -24;}
  }
  RECORD->verified_blocks=step+1;
 }
 if(!write_status(initial_status&0xbc)||!status(&protection)||
    (protection&0xfe)!=(initial_status&0xbc)){spi_close();return -25;}
#endif
 RECORD->phase=5;
 if(!scan(full,boot,outside,syscfg)){spi_close();return -26;}
 memcpy((void*)RECORD->after_hash,full,32);
 if(memcmp(syscfg,expected_syscfg,32)||memcmp(outside,expected_outside,32)){spi_close();return -27;}
#if WRITE_ENABLED
 if(memcmp(full,expected_after_full,32)||memcmp(boot,expected_target,32)){spi_close();return -28;}
#else
 if(memcmp(full,(const void*)RECORD->before_hash,32)){spi_close();return -29;}
#endif
 spi_close();RECORD->error_block=0xffffffff;return 0;
}
void main(void){
 memset((void*)RECORD,0,sizeof(*RECORD));RECORD->magic=0x314e5249;RECORD->version=1;RECORD->mode=MODE;RECORD->bytes=0x20000;RECORD->sector_size=4096;memcpy((void*)RECORD->nonce,run_nonce,16);
 int rc=main_logic();RECORD->error=rc?rc:io_error;RECORD->phase=RECORD->error?0xee:6;
 memcpy((void*)0x22010000,return_blob,return_blob_size);
 ((void(*)(void))0x22010000)();
 for(;;){} /* Terminal if the return trampoline unexpectedly returns. */
}
