import { useState, useEffect } from "react";

const API = "http://localhost:8000";

// Los precios en Chile no llevan decimales
const pesos = (n) =>
  n == null ? "—" : "$" + Math.round(n).toLocaleString("es-CL");

// La clave lleva barras verticales, que hay que codificar en la URL
const ruta = (base, clave) => `${API}/${base}/${encodeURIComponent(clave)}`;

const capitalizar = (t) =>
  t ? t.charAt(0).toUpperCase() + t.slice(1) : "";

// "500.0mg" se lee mejor como "500 mg"
function legibleConcentracion(c) {
  if (!c) return "";
  return c
    .replace(/(\d+)\.0(?=[a-z])/gi, "$1")
    .replace(/(\d)([a-z])/i, "$1 $2");
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
   El sello amarillo distingue lo certificado por el ISP de
   lo que solo declara la farmacia. No es lo mismo y el
   usuario debe poder notarlo.
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
      <span className="punto" />
      {certificado ? "Bioequivalente ISP" : "Bioequivalente según farmacia"}
    </span>
  );
}

/* --------------------- Tarjeta de presentación --------------------- */

function Tarjeta({ datos, activa, onAbrir }) {
  const envases = datos.envases || [];

  return (
    <button
      className="tarjeta"
      aria-pressed={activa}
      onClick={() => onAbrir(datos)}
    >
      <figure>
        {datos.url_imagen ? (
          <img src={datos.url_imagen} alt="" loading="lazy" />
        ) : (
          <span className="sin-foto">Sin fotografía</span>
        )}
      </figure>

      <div className="tarjeta-cuerpo">
        <div className="principio">{capitalizar(datos.principio_activo)}</div>
        <div className="dosis">
          {legibleConcentracion(datos.concentracion)}
          {datos.familia && ` · ${NOMBRE_FAMILIA[datos.familia] || datos.familia}`}
        </div>

        {datos.hay_bioequivalente && (
          <div style={{ marginTop: 10 }}>
            <span className="sello-bio declarado">
              <span className="punto" />
              Hay bioequivalentes
            </span>
          </div>
        )}

        <div className="tarjeta-pie">
          <div>
            <div className="desde">Desde</div>
            <div className="precio-principal">{pesos(datos.precio_desde)}</div>
          </div>
          <div className="donde">
            {envases.length === 1
              ? `${envases[0]} unidades`
              : `${envases.length} presentaciones`}
            <br />
            {datos.farmacias.length === 1 ? "1 farmacia" : `${datos.farmacias.length} farmacias`}
          </div>
        </div>
      </div>
    </button>
  );
}

/* --------------------- Comparación entre farmacias --------------------- */

function Comparacion({ clave }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDatos(null);
    setError(null);

    fetch(ruta("comparar", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setDatos)
      .catch(() => setError("No se pudieron cargar las opciones."));
  }, [clave]);

  if (error) return <p className="aviso">{error}</p>;
  if (!datos) return <p className="aviso">Cargando opciones…</p>;

  return (
    <>
      {datos.ahorro && datos.ahorro.monto > 0 && (
        <div className="resumen-ahorro">
          Entre la opción más económica y la más cara hay{" "}
          <strong>{pesos(datos.ahorro.monto)} de diferencia</strong>, un{" "}
          {datos.ahorro.porcentaje}% sobre el mismo medicamento y la misma
          cantidad.
        </div>
      )}

      <div className="opciones">
        {datos.productos.map((p, i) => (
          <article key={p.id} className={`opcion ${i === 0 ? "mejor" : ""}`}>
            <div>
              <div className="opcion-nombre">{p.nombre_publicado}</div>

              <div className="opcion-meta">
                <span className="farmacia">{p.farmacia}</span>
                {p.condicion_venta && <span>{capitalizar(p.condicion_venta.toLowerCase())}</span>}
                {p.fecha_muestreo && <span>Precio al {p.fecha_muestreo}</span>}
                <SelloBio valor={p.bioequivalente} fuente={p.bioequivalente_fuente} />
              </div>

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

              {p.nombre_oficial && (
                <div className="oficial">
                  Registro sanitario: {p.nombre_oficial}
                  {p.laboratorio_oficial && ` · ${p.laboratorio_oficial}`}
                </div>
              )}
            </div>

            <div className="opcion-precio">
              <div className="precio">{pesos(p.precio_oferta)}</div>
              {p.en_oferta && (
                <div className="precio-antes">{pesos(p.precio_normal)}</div>
              )}
              {p.precio_unitario && (
                <div className="unitario">{pesos(p.precio_unitario)} por unidad</div>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

/* --------------------- Detalle de una presentación --------------------- */

function Detalle({ presentacion }) {
  const [tamanios, setTamanios] = useState(null);
  const [elegido, setElegido] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setTamanios(null);
    setElegido(null);
    setError(null);

    fetch(ruta("presentacion", presentacion.clave_presentacion))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setTamanios(d.tamanios);
        // Se abre en el tamanio con mas opciones: es donde la
        // comparacion aporta mas
        const conMasOpciones = [...d.tamanios].sort(
          (a, b) => b.farmacias - a.farmacias
        )[0];
        if (conMasOpciones) setElegido(conMasOpciones.clave_equivalencia);
      })
      .catch(() => setError("No se pudo cargar esta presentación."));
  }, [presentacion.clave_presentacion]);

  const familia =
    NOMBRE_FAMILIA[presentacion.familia] || presentacion.familia;

  return (
    <section className="detalle">
      <h2 className="detalle-titulo">
        {capitalizar(presentacion.principio_activo)}{" "}
        {legibleConcentracion(presentacion.concentracion)}
      </h2>
      <p className="detalle-bajada">
        {capitalizar(familia)}. Elige la cantidad que necesitas: los precios
        solo se comparan entre envases del mismo tamaño.
      </p>

      {error && <p className="aviso">{error}</p>}
      {!tamanios && !error && <p className="aviso">Cargando presentaciones…</p>}

      {tamanios && (
        <div className="tamanios">
          {tamanios.map((t) => (
            <button
              key={t.clave_equivalencia}
              className="tamanio"
              aria-pressed={elegido === t.clave_equivalencia}
              onClick={() => setElegido(t.clave_equivalencia)}
            >
              <div className="tamanio-cantidad">
                {t.cantidad_envase} {t.unidad_envase}
              </div>
              <div className="tamanio-dato">
                {pesos(t.precio_min)}
                {t.farmacias > 1 && ` · ${t.farmacias} farmacias`}
              </div>
            </button>
          ))}
        </div>
      )}

      {elegido && <Comparacion clave={elegido} />}
    </section>
  );
}

/* --------------------- Aplicación --------------------- */

export default function App() {
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState(null);
  const [abierta, setAbierta] = useState(null);
  const [cobertura, setCobertura] = useState(null);

  useEffect(() => {
    fetch(`${API}/estadisticas`)
      .then((r) => r.json())
      .then(setCobertura)
      .catch(() => {});
  }, []);

  function buscar(termino) {
    const q = (termino ?? consulta).trim();
    if (q.length < 3) return;

    setConsulta(q);
    setBuscando(true);
    setError(null);
    setAbierta(null);

    fetch(`${API}/buscar?q=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setResultados(d))
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
        <div className="marca">
          bio<span>equi</span>
        </div>
        {cobertura && (
          <div className="cobertura">
            {cobertura.productos.toLocaleString("es-CL")} productos ·{" "}
            {cobertura.grupos_multiples} comparables entre farmacias
          </div>
        )}
      </header>

      <main className="envoltorio">
        <section className="portada">
          <h1>¿Qué medicamento necesitas?</h1>

          <div className="buscador">
            <input
              value={consulta}
              onChange={(e) => setConsulta(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && buscar()}
              placeholder="Escribe el nombre o el principio activo"
              aria-label="Buscar medicamento"
            />
            <button onClick={() => buscar()} disabled={consulta.trim().length < 3}>
              Buscar
            </button>
          </div>

          <div className="sugerencias">
            Prueba con{" "}
            {["paracetamol", "ibuprofeno", "omeprazol", "losartan"].map((t) => (
              <button key={t} onClick={() => buscar(t)}>
                {t}
              </button>
            ))}
          </div>
        </section>

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
                  activa={abierta?.clave_presentacion === p.clave_presentacion}
                  onAbrir={setAbierta}
                />
              ))}
            </div>
          </>
        )}

        {abierta && <Detalle presentacion={abierta} />}
      </main>

      <footer className="pie">
        <p>
          Los precios corresponden a la fecha de muestreo indicada en cada
          producto y pueden haber cambiado. BioEqui no vende medicamentos: los
          enlaces llevan al sitio de cada farmacia.
        </p>
        <p>
          La información es referencial y no reemplaza la indicación de un
          profesional de la salud. Existen medicamentos en los que la
          sustitución requiere supervisión médica.
        </p>
      </footer>
    </>
  );
}
