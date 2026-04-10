# Reglamento de Gestión — COCOS PESOS PLUS FCI

**Fuente:** PDF oficial descargado 2026-07-08  
**Inscripción CNV:** Nº 1611  
**Aprobación:** DI-2025-45-APN-GFCI#CNV de fecha 6 de junio de 2025  

## Partes

| Rol | Entidad | CNV |
|-----|---------|-----|
| Sociedad Gerente (Administrador) | COCOS ASSET MANAGEMENT S.A. | Nº 56 |
| Sociedad Depositaria (Custodio) | BANCO COMAFI S.A. | Nº 26 |

## Clasificación

- **Moneda:** Peso argentino (ARS)
- **Tipo CNV:** inciso (a), artículo 4, Capítulo II, Título V de las Normas CNV
  - **NO es mercado de dinero (money market).** Es un fondo de renta variable/mixta con política de inversión flexible.
- **Horizonte:** no especificado (cartera diversificada)

## Política de Inversión

Puede invertir hasta **100%** del patrimonio en:
- Acciones ordinarias/preferidas
- Certificados de participación de fideicomisos financieros
- CEVA, CEDEAR (con acuerdos internacionales)
- ONs, cédulas hipotecarias, valores de corto plazo
- Títulos de deuda pública nacional/provincial/municipal, LECAPs, BCRA
- Cheques diferidos, pagarés, facturas MiPyMEs

Hasta **25%** en:
- CEDEAR (no cubiertos por tratados)
- ADRs/BDRs/GDRs
- ETF internacionales
- Divisas

Hasta **20%** en:
- Plazos fijos, cauciones/pases, préstamos de valores, warrants

Hasta **5%** en:
- Cuotapartes de FCI cerrados

Derivados: permitidos con finalidad especulativa o de cobertura.  
Endeudamiento: hasta 50% del patrimonio neto vía pases/cauciones.

## Clases de Cuotapartes

| Clase | Suscriptor | Monto mínimo |
|-------|-----------|--------------|
| A | Personas humanas | – |
| B | Personas jurídicas | – |
| C | Personas jurídicas | ≥ $100.000.000 |
| D | Personas jurídicas | ≥ $2.000.000.000 |
| Ley 27.743 | Regularización de activos (blanqueo) | – |

## Comisiones (máximos)

- Administrador: 5% anual s/PN diario
- Custodio: 1% anual s/PN diario
- Gastos ordinarios: 4% anual s/PN diario
- Tope total: 10% anual
- Suscripción: hasta 3%
- Rescate: hasta 3%
- Transferencia: 0%

## Rescates

- Plazo máximo: 3 días hábiles
- Preaviso posible si rescates ≥ 15% del PN: hasta 3 días hábiles adicionales

## Cierre de Ejercicio

31 de diciembre de cada año.

## Implicancias para BuildFuture

- **COCOSPPA en IOL/ticker** mapea a este fondo (CNV Nº 1611)
- **NO es mercado de dinero** → no debe clasificarse en categoría `mercadoDinero` de CAFCI/ArgentinaDatos
- La categoría correcta en ArgentinaDatos sería `rentaMixta` o `rentaVariable`
- El yield que muestra Cocos app (TEA ~35%) es el rendimiento histórico de la cartera flexible, no un money market
- Para calcular yield exacto: buscar en ArgentinaDatos por nombre "Cocos Pesos Plus" en las categorías non-mercadoDinero
