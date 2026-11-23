import { useState, useEffect, useRef } from "react";

const API = "http://localhost:8000";

// Los precios en Chile no llevan decimales
const pesos = (n) =>
  n == null ? "—" : "$" + Math.round(n).toLocaleString("es-CL");

// La clave lleva barras verticales, que hay que codificar en la URL
const ruta = (base, clave) => `${API}/${base}/${encodeURIComponent(clave)}`;

const capitalizar = (t) =>
  t ? t.charAt(0).toUpperCase() + t.slice(1) : "";

// "500.0mg" se lee mejor como "500 mg"; en los combinados,
// "875+125mg" se lee "875 mg + 125 mg"
function legibleConcentracion(c) {
  if (!c) return "";
  const m = c.match(/^([\d.+]+)(mg(?:\/ml)?)$/);
  if (m && m[1].includes("+")) {
    const [unidad, porMl] = m[2].split("/");
    return (
      m[1].split("+").map((d) => `${d} ${unidad}`).join(" + ") +
      (porMl ? " por ml" : "")
    );
  }
  return c
    .replace(/(\d+)\.0(?=[a-z])/gi, "$1")
    .replace(/(\d)([a-z])/i, "$1 $2");
}

// Nombre del medicamento con su dosis. Un combinado muestra la dosis
// de cada principio activo cuando la API puede determinarla
function tituloMedicamento(datos) {
  if (datos.dosis_detalle) return capitalizar(datos.dosis_detalle);
  const principio = (datos.principio_activo || "").split("+").join(" + ");
  return `${capitalizar(principio)} ${legibleConcentracion(datos.concentracion)}`;
}

const NOMBRE_FAMILIA = {
  solido_oral: "comprimidos o cápsulas",
  liberacion_modificada: "liberación prolongada",
  liquido_oral: "jarabe, gotas o solución",
  inyectable: "inyectable",
  topico: "uso tópico",
  oftalmico: "gotas oftálmicas",
  otico: "gotas óticas",
  nasal: "uso nasal",
  rectal: "supositorios",
  vaginal: "óvulos",
  sublingual: "sublingual",
  inhalatorio: "inhalación",
  transdermico: "parches",
};

/* ---------------------------------------------------------
   El sello amarillo imita el que llevan las cajas de los
   medicamentos bioequivalentes en Chile. Se reserva para lo
   certificado por el ISP; lo que solo declara la farmacia va
   en el color de la marca, para que no se confundan.
   --------------------------------------------------------- */
function SelloBio({ valor, fuente }) {
  if (!valor) return null;

  const certificado = fuente === "isp";

  return (
    <span
      className={`sello-bio ${certificado ? "certificado" : "declarado"}`}
      title={
        certificado
          ? "Bioequivalencia certificada por el Instituto de Salud Pública"
          : "Bioequivalencia declarada por la farmacia, sin verificar contra el registro del ISP"
      }
    >
      {certificado && <span className="sello-be" aria-hidden="true">BE</span>}
      {certificado ? "Bioequivalente certificado ISP" : "Bioequivalente según la farmacia"}
    </span>
  );
}

/* --------------------- Gráfico de precio histórico --------------------- */

// "2026-09-07" -> "7 sept". Se arma la fecha a mano para que la zona
// horaria no la corra un dia
const fechaCorta = (iso) => {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
  });
};

const fechaLarga = (iso) => {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
};

// Escala "redonda" para el eje: 0, 1.000, 2.000... en vez de 0, 873, 1.746
function marcasEje(maximo, cantidad = 4) {
  if (!maximo) return [0];
  const bruto = maximo / cantidad;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((x) => x * potencia).find((x) => x >= bruto);
  const marcas = [];
  for (let v = 0; v <= maximo + paso * 0.001; v += paso) marcas.push(v);
  if (marcas[marcas.length - 1] < maximo) marcas.push(marcas[marcas.length - 1] + paso);
  return marcas;
}

const ALTO = 240;
const MARGEN = { arriba: 16, derecha: 16, abajo: 32, izquierda: 64 };

// serie: [{ fecha, precio, nota }] ordenada por fecha
function GraficoHistorial({ serie, descripcion }) {
  const contenedor = useRef(null);
  const [ancho, setAncho] = useState(480);
  const [foco, setFoco] = useState(null);

  // El SVG se dibuja al ancho real para que el texto no se deforme
  useEffect(() => {
    const nodo = contenedor.current;
    if (!nodo) return;
    const observador = new ResizeObserver(([e]) => setAncho(e.contentRect.width));
    observador.observe(nodo);
    return () => observador.disconnect();
  }, []);

  const tiempos = serie.map((p) => {
    const [a, m, d] = p.fecha.split("-").map(Number);
    return Date.UTC(a, m - 1, d);
  });
  const marcas = marcasEje(Math.max(...serie.map((p) => p.precio)));
  const tope = marcas[marcas.length - 1];

  const interior = ancho - MARGEN.izquierda - MARGEN.derecha;
  const t0 = tiempos[0];
  const rango = tiempos[tiempos.length - 1] - t0 || 1;
  const x = (i) => MARGEN.izquierda + ((tiempos[i] - t0) / rango) * interior;
  const y = (v) => MARGEN.arriba + (1 - v / tope) * (ALTO - MARGEN.arriba - MARGEN.abajo);

  const trazo = serie.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.precio)}`).join(" ");

  // Etiquetas del eje x: primera, ultima y las intermedias que no se
  // encimen. Se mide en pixeles porque las fechas no son equidistantes
  const SEPARACION = 70;
  const ultima = serie.length - 1;
  const etiquetasX = [0];
  for (let i = 1; i < ultima; i++) {
    const libre =
      x(i) - x(etiquetasX[etiquetasX.length - 1]) >= SEPARACION &&
      x(ultima) - x(i) >= SEPARACION;
    if (libre) etiquetasX.push(i);
  }
  if (ultima > 0 && x(ultima) - x(0) >= SEPARACION) etiquetasX.push(ultima);

  function alMover(e) {
    const caja = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - caja.left;
    let cercano = 0;
    serie.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(cercano) - px)) cercano = i;
    });
    setFoco(cercano);
  }

  const punto = foco != null ? serie[foco] : null;

  return (
    <div className="grafico" ref={contenedor}>
      <svg
        width={ancho}
        height={ALTO}
        role="img"
        aria-label={`${descripcion}, entre el ${fechaLarga(serie[0].fecha)} y el ${fechaLarga(serie[ultima].fecha)}`}
        onPointerMove={alMover}
        onPointerLeave={() => setFoco(null)}
      >
        {marcas.map((v) => (
          <g key={v}>
            <line
              className="grafico-reja"
              x1={MARGEN.izquierda}
              x2={ancho - MARGEN.derecha}
              y1={y(v)}
              y2={y(v)}
            />
            <text className="grafico-eje" x={MARGEN.izquierda - 10} y={y(v)} dy="0.32em" textAnchor="end">
              {pesos(v)}
            </text>
          </g>
        ))}

        {etiquetasX.map((i) => (
          <text
            key={i}
            className="grafico-eje"
            x={x(i)}
            y={ALTO - 8}
            textAnchor={i === 0 ? "start" : i === ultima ? "end" : "middle"}
          >
            {fechaCorta(serie[i].fecha)}
          </text>
        ))}

        <path className="grafico-linea" d={trazo} />

        {serie.map((p, i) => (
          <circle key={p.fecha} className="grafico-marca" cx={x(i)} cy={y(p.precio)} r={2.5} />
        ))}

        {punto && (
          <g>
            <line
              className="grafico-guia"
              x1={x(foco)}
              x2={x(foco)}
              y1={MARGEN.arriba}
              y2={ALTO - MARGEN.abajo}
            />
            <circle className="grafico-punto" cx={x(foco)} cy={y(punto.precio)} r={5} />
          </g>
        )}
      </svg>

      {punto && (
        <div
          className="grafico-tooltip"
          style={{
            left: Math.min(Math.max(x(foco), 90), ancho - 90),
            top: y(punto.precio),
          }}
        >
          <strong>{pesos(punto.precio)}</strong>
          <span>{fechaLarga(punto.fecha)}</span>
          {punto.nota && <span>{punto.nota}</span>}
        </div>
      )}
    </div>
  );
}

/* --------------------- Historial de precios --------------------- */

// Valor especial del selector para la serie de todo el grupo
const MERCADO = "mercado";

// Las dos fuentes entregan formatos distintos; se llevan al mismo
// { fecha, precio, nota } que dibuja el grafico
function serieMercado(datos) {
  return datos.serie.map((p) => ({
    fecha: p.fecha_muestreo,
    precio: p.precio_min,
    nota: `${p.farmacias} ${p.farmacias === 1 ? "farmacia" : "farmacias"} con precio`,
  }));
}

function serieProducto(datos) {
  return datos.historial
    .filter((h) => h.precio_oferta > 0)
    .map((h) => ({
      fecha: h.fecha_muestreo,
      precio: h.precio_oferta,
      nota:
        h.disponible === false
          ? "Sin stock ese día"
          : h.descuento_pct
            ? `En oferta, antes ${pesos(h.precio_normal)}`
            : null,
    }));
}

function Historial({ clave, productos, seleccion, alCambiar }) {
  const [serie, setSerie] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setSerie(null);
    setError(null);

    const url =
      seleccion === MERCADO ? ruta("historial", clave) : `${API}/producto/${seleccion}`;

    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setSerie(seleccion === MERCADO ? serieMercado(d) : serieProducto(d)))
      .catch(() => setError("No se pudo cargar el historial de precios."));
  }, [clave, seleccion]);

  const elegido = productos.find((p) => p.id === seleccion);
  const descripcion = elegido
    ? `Precio en ${elegido.farmacia}`
    : "Precio más bajo entre todas las farmacias";

  let contenido;
  if (error) {
    contenido = <p className="aviso">{error}</p>;
  } else if (!serie) {
    contenido = <p className="aviso">Cargando historial…</p>;
  } else if (serie.length < 2) {
    contenido = (
      <p className="aviso">
        Todavía hay una sola medición de precio
        {elegido ? ` en ${elegido.farmacia}` : ""}
        {serie.length === 1 && `: ${pesos(serie[0].precio)} el ${fechaLarga(serie[0].fecha)}`}.
        El gráfico aparecerá cuando se acumulen más fechas.
        {elegido && (
          <button className="enlace" onClick={() => alCambiar(MERCADO)}>
            Ver el precio más bajo entre farmacias
          </button>
        )}
      </p>
    );
  } else {
    const precios = serie.map((p) => p.precio);
    const primero = precios[0];
    const ultimo = precios[precios.length - 1];
    const cambio = primero ? Math.round((100 * (ultimo - primero)) / primero) : 0;

    contenido = (
      <>
        <dl className="historial-cifras">
          <div>
            <dt>Último precio</dt>
            <dd>{pesos(ultimo)}</dd>
          </div>
          <div>
            <dt>Mínimo</dt>
            <dd>{pesos(Math.min(...precios))}</dd>
          </div>
          <div>
            <dt>Máximo</dt>
            <dd>{pesos(Math.max(...precios))}</dd>
          </div>
          <div>
            <dt>Desde el {fechaCorta(serie[0].fecha)}</dt>
            <dd className={cambio > 0 ? "sube" : cambio < 0 ? "baja" : ""}>
              {cambio > 0 ? "+" : cambio < 0 ? "−" : ""}
              {Math.abs(cambio)}%
            </dd>
          </div>
        </dl>

        <GraficoHistorial serie={serie} descripcion={descripcion} />

        <details className="historial-tabla">
          <summary>Ver los datos en una tabla</summary>
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Precio</th>
                <th>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {serie.map((p) => (
                <tr key={p.fecha}>
                  <td>{fechaLarga(p.fecha)}</td>
                  <td>{pesos(p.precio)}</td>
                  <td>{p.nota || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </>
    );
  }

  return (
    <div className="historial">
      <label className="historial-selector">
        <span>Ver el historial de</span>
        <select
          value={seleccion}
          onChange={(e) =>
            alCambiar(e.target.value === MERCADO ? MERCADO : Number(e.target.value))
          }
        >
          <option value={MERCADO}>El precio más bajo entre farmacias</option>
          {productos.map((p) => (
            <option key={p.id} value={p.id}>
              {p.farmacia}, {pesos(p.precio_oferta)}: {p.nombre_publicado}
            </option>
          ))}
        </select>
      </label>

      {contenido}
    </div>
  );
}

/* --------------------- Tarjeta de resultado --------------------- */

function Tarjeta({ datos, href }) {
  const envases = datos.envases || [];
  const familia = NOMBRE_FAMILIA[datos.familia] || datos.familia;

  return (
    <a className="tarjeta" href={href}>
      <figure>
        {datos.url_imagen ? (
          <img src={datos.url_imagen} alt="" loading="lazy" />
        ) : (
          <span className="sin-foto">Sin fotografía</span>
        )}
      </figure>

      <div className="tarjeta-cuerpo">
        <h3 className="principio">{tituloMedicamento(datos)}</h3>
        {familia && <p className="dosis">{capitalizar(familia)}</p>}

        <div className="tarjeta-pie">
          <div>
            <span className="desde">Desde</span>
            <span className="precio-principal">{pesos(datos.precio_desde)}</span>
          </div>
          <p className="donde">
            {envases.length === 1
              ? `Envase de ${envases[0]}`
              : `${envases.length} tamaños de envase`}
            <br />
            {datos.farmacias.length === 1
              ? "En 1 farmacia"
              : `En ${datos.farmacias.length} farmacias`}
          </p>
        </div>

        {datos.hay_bioequivalente && (
          <p className="tarjeta-nota">Tiene opciones bioequivalentes</p>
        )}
      </div>
    </a>
  );
}

/* --------------------- Opciones de compra + historial --------------------- */

function Presentacion({ clave, tamanio }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  const [seleccion, setSeleccion] = useState(null);
  const panelHistorial = useRef(null);

  useEffect(() => {
    setDatos(null);
    setError(null);
    setSeleccion(null);

    fetch(ruta("comparar", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setDatos(d);
        // Se parte por la serie de todo el grupo: siempre tiene mas
        // fechas que cualquier farmacia por separado
        setSeleccion(MERCADO);
      })
      .catch(() => setError("No se pudieron cargar las opciones."));
  }, [clave]);

  function elegir(id) {
    setSeleccion(id);
    // En pantallas angostas el grafico queda abajo de la lista: se
    // lleva la vista hasta el para que se note el cambio
    if (window.matchMedia("(max-width: 900px)").matches) {
      panelHistorial.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  if (error) return <p className="aviso">{error}</p>;
  if (!datos || seleccion == null) return <p className="aviso">Cargando opciones…</p>;

  return (
    <div className="columnas">
      <section className="bloque">
        <h2 className="paso">Dónde comprarlo</h2>
        <p className="paso-ayuda">
          {tamanio && `Envase de ${tamanio.cantidad_envase} ${tamanio.unidad_envase}, `}
          del más barato al más caro. Elige una farmacia para ver cómo ha
          cambiado su precio.
        </p>

        {datos.ahorro && datos.ahorro.monto > 0 && (
          <p className="resumen-ahorro">
            Entre la opción más barata y la más cara hay{" "}
            <strong>{pesos(datos.ahorro.monto)} de diferencia</strong> por el
            mismo medicamento y la misma cantidad.
          </p>
        )}

        <ul className="opciones">
          {datos.productos.map((p, i) => {
            const activa = seleccion === p.id;
            return (
              <li
                key={p.id}
                className={`opcion${i === 0 ? " mejor" : ""}${activa ? " activa" : ""}`}
              >
                <button
                  className="opcion-elegir"
                  aria-pressed={activa}
                  onClick={() => elegir(p.id)}
                >
                  <span className="opcion-foto" aria-hidden="true">
                    {p.url_imagen && <img src={p.url_imagen} alt="" loading="lazy" />}
                  </span>

                  <span className="opcion-texto">
                    <span className="opcion-farmacia">
                      {p.farmacia}
                      {i === 0 && <span className="etiqueta-mejor">Más barato</span>}
                    </span>
                    <span className="opcion-nombre">{p.nombre_publicado}</span>
                    {p.condicion_venta && (
                      <span className="opcion-meta">
                        {capitalizar(p.condicion_venta.toLowerCase())}
                      </span>
                    )}
                  </span>

                  <span className="opcion-precio">
                    <span className="precio">{pesos(p.precio_oferta)}</span>
                    {p.en_oferta && (
                      <span className="precio-antes">{pesos(p.precio_normal)}</span>
                    )}
                    {p.precio_unitario && (
                      <span className="unitario">{pesos(p.precio_unitario)} c/u</span>
                    )}
                  </span>
                </button>

                <div className="opcion-pie">
                  <SelloBio valor={p.bioequivalente} fuente={p.bioequivalente_fuente} />
                  {p.url_producto && (
                    <a
                      className="ir"
                      href={p.url_producto}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Ver en {p.farmacia}
                    </a>
                  )}
                </div>

                {p.nombre_oficial && (
                  <p className="oficial">
                    Registro ISP: {p.nombre_oficial}
                    {p.laboratorio_oficial && `, ${p.laboratorio_oficial}`}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="bloque bloque-historial" ref={panelHistorial}>
        <h2 className="paso">Precio en el tiempo</h2>
        <Historial
          clave={clave}
          productos={datos.productos}
          seleccion={seleccion}
          alCambiar={setSeleccion}
        />
      </section>
    </div>
  );
}

/* --------------------- Navegación --------------------- */

// Rutas en el hash (#/medicamento/<clave>): no requieren configurar el
// servidor, el boton Atras del navegador funciona y el enlace se puede
// compartir.
const PREFIJO_MEDICAMENTO = "#/medicamento/";

const enlaceMedicamento = (clave) =>
  PREFIJO_MEDICAMENTO + encodeURIComponent(clave);

function leerRuta() {
  const hash = window.location.hash;
  if (hash.startsWith(PREFIJO_MEDICAMENTO)) {
    return { pagina: "medicamento", clave: decodeURIComponent(hash.slice(PREFIJO_MEDICAMENTO.length)) };
  }
  return { pagina: "inicio" };
}

function useRuta() {
  const [ruta, setRuta] = useState(leerRuta);

  useEffect(() => {
    const alCambiar = () => {
      setRuta(leerRuta());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);

  return ruta;
}

/* --------------------- Página de un medicamento --------------------- */

function PaginaMedicamento({ clave, hayBusqueda }) {
  const [datos, setDatos] = useState(null);
  const [elegido, setElegido] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDatos(null);
    setElegido(null);
    setError(null);

    fetch(ruta("presentacion", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setDatos(d);
        // Se abre en el tamanio con mas opciones: es donde la
        // comparacion aporta mas
        const conMasOpciones = [...d.tamanios].sort(
          (a, b) => b.farmacias - a.farmacias
        )[0];
        if (conMasOpciones) setElegido(conMasOpciones.clave_equivalencia);
      })
      .catch((estado) =>
        setError(
          estado === 404
            ? "Este medicamento ya no tiene precios disponibles."
            : "No se pudo cargar este medicamento. Revisa que la API esté corriendo."
        )
      );
  }, [clave]);

  // Si se llego desde una busqueda, volver la deja tal como estaba
  function volver(e) {
    if (hayBusqueda) {
      e.preventDefault();
      window.history.back();
    }
  }

  const tamanio = datos?.tamanios.find((t) => t.clave_equivalencia === elegido);

  return (
    <main className="envoltorio pagina-medicamento">
      <a className="volver" href="#/" onClick={volver}>
        {hayBusqueda ? "Volver a los resultados" : "Buscar otro medicamento"}
      </a>

      {error && <p className="aviso">{error}</p>}
      {!datos && !error && <p className="aviso">Cargando medicamento…</p>}

      {datos && (
        <>
          <header className="detalle-cabecera">
            <figure className="detalle-foto">
              {datos.url_imagen ? (
                <img src={datos.url_imagen} alt="" />
              ) : (
                <span className="sin-foto">Sin fotografía</span>
              )}
            </figure>
            <div>
              <h1 className="detalle-titulo">{tituloMedicamento(datos)}</h1>
              <p className="detalle-bajada">
                {capitalizar(NOMBRE_FAMILIA[datos.familia] || datos.familia)}
              </p>
              <p className="detalle-datos">
                Desde <strong>{pesos(datos.precio_desde)}</strong> en{" "}
                {datos.farmacias.length}{" "}
                {datos.farmacias.length === 1 ? "farmacia" : "farmacias"}
                {datos.hay_bioequivalente && ", con opciones bioequivalentes"}
              </p>
            </div>
          </header>

          <section className="tamanios-bloque">
            <h2 className="paso">¿Qué cantidad necesitas?</h2>
            <p className="paso-ayuda">
              Los precios solo se comparan entre envases del mismo tamaño.
            </p>
            <div className="tamanios" role="group" aria-label="Tamaño del envase">
              {datos.tamanios.map((t) => (
                <button
                  key={t.clave_equivalencia}
                  className="tamanio"
                  aria-pressed={elegido === t.clave_equivalencia}
                  onClick={() => setElegido(t.clave_equivalencia)}
                >
                  <span className="tamanio-cantidad">
                    {t.cantidad_envase} {t.unidad_envase}
                  </span>
                  <span className="tamanio-dato">
                    desde {pesos(t.precio_min)}
                    {t.farmacias > 1 && `, ${t.farmacias} farmacias`}
                  </span>
                </button>
              ))}
            </div>
          </section>

          {elegido && <Presentacion clave={elegido} tamanio={tamanio} />}
        </>
      )}
    </main>
  );
}

/* --------------------- Página de inicio --------------------- */

// Caso real que se muestra en la portada. Si algun dia deja de existir
// en la base, el panel simplemente no aparece
const EJEMPLO = "losartan|50.0mg|solido_oral|30comprimidos";
const EJEMPLO_PRESENTACION = "losartan|50.0mg|solido_oral";

// "Farmacias Cruz Verde" -> "Cruz Verde"; los nombres completos no caben
// junto a una barra
const farmaciaCorta = (nombre) =>
  nombre
    .replace(/^Farmacias? (del )?/i, "")
    .replace(/ Chilena contra la Epilepsia/i, "");

// La marca es lo que distingue una fila de otra: "Cozaar 50 mg x 30..." -> "Cozaar"
const marcaCorta = (nombre) => {
  const primera = (nombre || "").split(/\s+/)[0] || "";
  return capitalizar(primera.toLowerCase());
};

function EjemploPrecios() {
  const [datos, setDatos] = useState(null);

  useEffect(() => {
    fetch(ruta("comparar", EJEMPLO))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setDatos)
      .catch(() => {});
  }, []);

  if (!datos || datos.productos.length < 2) return null;

  const filas = datos.productos.slice(0, 7);
  const maximo = Math.max(...filas.map((p) => p.precio_oferta));
  const fecha = filas[0].fecha_muestreo;

  return (
    <a className="ejemplo" href={enlaceMedicamento(EJEMPLO_PRESENTACION)}>
      <h2 className="ejemplo-titulo">Losartán 50 mg, caja de 30 comprimidos</h2>
      <p className="ejemplo-bajada">
        El mismo medicamento en distintas farmacias
        {fecha && `, precios al ${fechaLarga(fecha)}`}.
      </p>

      <ul className="barras">
        {filas.map((p, i) => (
          <li
            key={p.id}
            className={i === 0 ? "barra-fila mas-barato" : "barra-fila"}
            title={`${p.farmacia}: ${p.nombre_publicado}, ${pesos(p.precio_oferta)}`}
          >
            <span className="barra-nombre">
              <span>{farmaciaCorta(p.farmacia)}</span>
              <span className="barra-marca">{marcaCorta(p.nombre_publicado)}</span>
            </span>
            <span className="barra-pista">
              <span
                className="barra-relleno"
                style={{ width: `${Math.max(2, (100 * p.precio_oferta) / maximo)}%` }}
              />
            </span>
            <span className="barra-precio">{pesos(p.precio_oferta)}</span>
          </li>
        ))}
      </ul>

      {datos.ahorro && (
        <p className="ejemplo-pie">
          Elegir bien ahorra hasta <strong>{pesos(datos.ahorro.monto)}</strong> en
          una sola caja.
          <span className="ejemplo-enlace">Ver la comparación completa</span>
        </p>
      )}
    </a>
  );
}

const PASOS = [
  {
    titulo: "Busca el medicamento",
    texto: "Escribe el nombre comercial o el principio activo, por ejemplo losartán o ibuprofeno.",
  },
  {
    titulo: "Elige la dosis y el envase",
    texto:
      "Solo comparamos productos con el mismo principio activo, la misma dosis y la misma cantidad.",
  },
  {
    titulo: "Compara y revisa el historial",
    texto: "Mira qué farmacia lo vende más barato hoy y cómo ha cambiado su precio.",
  },
];

function Informacion({ farmacias }) {
  const actualizacion = farmacias
    ?.map((f) => f.ultima_actualizacion)
    .filter(Boolean)
    .sort()
    .pop();

  return (
    <div className="informacion">
      <section className="seccion">
        <h2 className="seccion-titulo">Cómo funciona</h2>
        <ol className="pasos">
          {PASOS.map((p) => (
            <li key={p.titulo}>
              <h3>{p.titulo}</h3>
              <p>{p.texto}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="seccion bioeq">
        <div className="bioeq-texto">
          <h2 className="seccion-titulo">¿Qué es un medicamento bioequivalente?</h2>
          <p>
            Es un medicamento que demostró ante el Instituto de Salud Pública
            (ISP) que actúa en el organismo igual que el original: mismo
            principio activo, misma dosis y mismo efecto. Por eso puedes cambiar
            una marca por otra más barata.
          </p>
          <p className="bioeq-nota">
            Antes de cambiar un medicamento, consulta con tu médico o con el
            químico farmacéutico.
          </p>
        </div>

        <dl className="bioeq-tipos">
          <div>
            <dt>
              <span className="sello-be grande" aria-hidden="true">BE</span>
              Bioequivalente certificado ISP
            </dt>
            <dd>
              Comprobamos el registro sanitario del producto contra el registro
              oficial del ISP.
            </dd>
          </div>
          <div>
            <dt>Bioequivalente según la farmacia</dt>
            <dd>
              La farmacia lo declara, pero no pudimos comprobarlo en el registro
              del ISP.
            </dd>
          </div>
        </dl>
      </section>

      {farmacias?.length > 0 && (
        <section className="seccion">
          <h2 className="seccion-titulo">Farmacias que comparamos</h2>
          {actualizacion && (
            <p className="seccion-bajada">
              Precios actualizados al {fechaLarga(actualizacion)}.
            </p>
          )}
          <ul className="farmacias">
            {farmacias.map((f) => (
              <li key={f.codigo}>
                <a href={f.url_base} target="_blank" rel="noopener noreferrer">
                  {f.nombre}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function PaginaInicio({ busqueda, cobertura, farmacias }) {
  const { consulta, setConsulta, resultados, buscando, error, buscar } = busqueda;
  const n = (v) => v.toLocaleString("es-CL");
  const sinBusqueda = !resultados && !buscando && !error;

  return (
    <>
      <section className="portada">
        <div className="portada-contenido">
          <div className="portada-texto">
          <h1>¿Qué medicamento necesitas?</h1>
          <p className="portada-bajada">
            Busca por nombre o principio activo y compara el precio del mismo
            medicamento, en la misma dosis y cantidad, entre farmacias.
          </p>

          <form
            className="buscador"
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              buscar();
            }}
          >
            <svg className="buscador-icono" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="10.5" cy="10.5" r="6.5" />
              <line x1="15.5" y1="15.5" x2="21" y2="21" />
            </svg>
            <input
              value={consulta}
              onChange={(e) => setConsulta(e.target.value)}
              placeholder="Ej: paracetamol, losartán, omeprazol"
              aria-label="Buscar medicamento"
            />
            <button type="submit" disabled={consulta.trim().length < 3}>
              Buscar
            </button>
          </form>

          <div className="sugerencias">
            <span>Prueba con</span>
            {["paracetamol", "ibuprofeno", "omeprazol", "losartan"].map((t) => (
              <button key={t} type="button" onClick={() => buscar(t)}>
                {t}
              </button>
            ))}
          </div>

          {cobertura && (
            <p className="cobertura">
              {n(cobertura.productos)} productos de farmacias chilenas,{" "}
              {n(cobertura.grupos_multiples)} medicamentos que puedes comparar
              entre farmacias y {n(cobertura.medicamentos_isp)} registros del
              ISP para verificar la bioequivalencia.
            </p>
          )}
          </div>

          <EjemploPrecios />
        </div>
      </section>

      {sinBusqueda && <Informacion farmacias={farmacias} />}

      <main className={sinBusqueda ? "envoltorio vacio" : "envoltorio"}>
        {error && (
          <p className="aviso">
            <strong>No hay conexión con el servidor</strong>
            {error}
          </p>
        )}

        {buscando && <p className="aviso">Buscando…</p>}

        {resultados && !buscando && resultados.total === 0 && (
          <p className="aviso">
            <strong>Sin resultados para "{resultados.consulta}"</strong>
            Prueba con el principio activo en lugar del nombre comercial.
          </p>
        )}

        {resultados && !buscando && resultados.total > 0 && (
          <>
            <div className="encabezado-seccion">
              <h2>
                {resultados.total}{" "}
                {resultados.total === 1 ? "presentación" : "presentaciones"} de{" "}
                {resultados.consulta}
              </h2>
              <p>Elige una para comparar precios</p>
            </div>

            <div className="rejilla">
              {resultados.presentaciones.map((p) => (
                <Tarjeta
                  key={p.clave_presentacion}
                  datos={p}
                  href={enlaceMedicamento(p.clave_presentacion)}
                />
              ))}
            </div>
          </>
        )}
      </main>
    </>
  );
}

/* --------------------- Aplicación --------------------- */

export default function App() {
  const rutaActual = useRuta();
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState(null);
  const [cobertura, setCobertura] = useState(null);
  const [farmacias, setFarmacias] = useState(null);

  useEffect(() => {
    fetch(`${API}/estadisticas`)
      .then((r) => r.json())
      .then(setCobertura)
      .catch(() => {});
    fetch(`${API}/farmacias`)
      .then((r) => r.json())
      .then((d) => setFarmacias(d.farmacias))
      .catch(() => {});
  }, []);

  function buscar(termino) {
    const q = (termino ?? consulta).trim();
    if (q.length < 3) return;

    setConsulta(q);
    setBuscando(true);
    setError(null);

    fetch(`${API}/buscar?q=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setResultados(d);
        // Si hay una sola presentacion no hay nada que elegir: se abre
        // directamente
        if (d.total === 1) {
          window.location.hash = enlaceMedicamento(d.presentaciones[0].clave_presentacion);
        }
      })
      .catch(() =>
        setError(
          "No se pudo conectar con el servidor. Revisa que la API esté corriendo en el puerto 8000."
        )
      )
      .finally(() => setBuscando(false));
  }

  return (
    <>
      <header className="barra">
        <a className="marca" href="#/">
          <span className="marca-icono" aria-hidden="true" />
          BioEqui
        </a>
        <span className="barra-lema">Compara precios de medicamentos en Chile</span>
      </header>

      {rutaActual.pagina === "medicamento" ? (
        <PaginaMedicamento clave={rutaActual.clave} hayBusqueda={resultados != null} />
      ) : (
        <PaginaInicio
          cobertura={cobertura}
          farmacias={farmacias}
          busqueda={{ consulta, setConsulta, resultados, buscando, error, buscar }}
        />
      )}

      <footer className="pie">
        <p>
          Los precios corresponden a la fecha de medición indicada y pueden
          haber cambiado. BioEqui no vende medicamentos: los enlaces llevan al
          sitio de cada farmacia.
        </p>
        <p>
          La información es referencial y no reemplaza la indicación de un
          profesional de la salud. En algunos medicamentos la sustitución
          requiere supervisión médica.
        </p>
      </footer>
    </>
  );
}
