/* The master remains awake (SPI_ERR_02); no deep-sleep bank retention claim.
 * Keep selected v2 DMA/wire storage out of the already occupied BANK0. */
SECTIONS
{
    .bodaqs_spi_buffers : {} > SRAM_BANK1
    .bodaqs_crc_table : {} > SRAM_BANK1
}
