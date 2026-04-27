

"""
source .venv/bin/activate 

gdaldem color-relief \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_expanding_classified.tif \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/color.txt \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_expanding_rgba.tif\
    -alpha

gdaldem color-relief \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_contraction_classified.tif \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/color.txt \
    /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_contraction_rgba.tif \
    -alpha

#30 m raster → max zoom 13 or 14
#10 m raster → max zoom 14 or 15   

gdal2tiles.py \
  --xyz \
  -z 4-13 \
  -r near \
  -w none \
  /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_expanding_rgba.tif \
  /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic_tiles/expanding


gdal2tiles.py \
  --xyz \
  -z 4-13 \
  -r near \
  -w none \
  /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic/KSA_cpf_contraction_rgba.tif \
  /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/cpf_dynamic_tiles/contraction
"""
